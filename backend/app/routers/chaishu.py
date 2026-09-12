"""拆书官平移(F11)+ 素材库挂载 + MCP 查证(F12)。

- 拆书导入:旧系统拆书成果(17 维度目录树)→ 映射到 L1 六类提案区(source=import);
  文风.md → 风格指纹提案(蒸馏管道产物,人批准生效);
  收尾校验 = 旧系统 check-chaishu.js 的等价物(必备文件/设定完整性/章节覆盖)。
- 素材库只读浏览 + 标记进装配池(= 导入为 L1 提案)。
- 查证:MCP 官方 SDK stdio 白名单制,wiki 优先、tavily 降级(旧系统纪律);
  取证落素材库(来源/时间/置信度)——大文件拆分批(2026-09-10)整域抽至
  chaishu_verify.py(本件 include_router 挂载,URL 零变化)。
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now, _prompt
from ..db import tx
from ..ledger.usage import chat_completion
from ..llm.atomic_io import write_text_atomic
from ..settings_store import get_settings, touch_prompt_append
from .chaishu_verify import verify_router

router = APIRouter(prefix="/api/chaishu", tags=["chaishu"])

ASSETS_DIR = Path(__file__).resolve().parents[3] / "可用" / "自家家具-桶0"

# 拆书成果 → L1 类别映射(文件名包含即命中;顺序即优先级)
CATEGORY_MAP = [
    ("角色", "character"),
    ("功法体系", "power"),
    ("力量体系", "power"),
    ("势力", "faction"),
    ("地理", "map"),
    ("物品", "item_economy"),
    ("货币", "item_economy"),
    ("背景设定", "worldview"),
    ("世界观", "worldview"),
]




def _safe_dir(path: str) -> Path:
    """只允许浏览可用素材库内的目录(白名单根)。"""
    root = ASSETS_DIR.resolve()
    target = Path(path).resolve() if path else root
    if root not in target.parents and target != root:
        raise HTTPException(403, "只允许浏览可用素材库内的目录")
    if not target.exists():
        raise HTTPException(404, "目录不存在")
    return target


@router.get("/browse")
def browse(path: str = "") -> dict:
    target = _safe_dir(path)
    items = []
    for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
        items.append({"name": p.name, "dir": p.is_dir(),
                      "size": p.stat().st_size if p.is_file() else None})
    return {"path": str(target), "parent": str(target.parent) if target != ASSETS_DIR.resolve() else None,
            "items": items}


@router.get("/file")
def read_file(path: str) -> dict:
    target = _safe_dir(path)
    if not target.is_file():
        raise HTTPException(422, "不是文件")
    if target.suffix.lower() not in (".md", ".txt", ".json"):
        raise HTTPException(422, "只支持 md/txt/json 预览")
    # 20000:预览只回文件头部供抽查,不整本下发
    return {"path": str(target), "content": target.read_text(encoding="utf-8", errors="ignore")[:20000]}


def _validate_chaishu(root: Path) -> dict:
    """收尾校验:旧系统 check-chaishu.js 的 Python 等价物。"""
    book = next((d for d in root.iterdir() if d.is_dir()), None)
    if book is None:
        return {"pass": False, "problems": ["未找到拆书作品目录"], "book_dir": ""}
    checks = {
        "必备文件概要": (book / "概要.md").exists(),
        "必备文件拆文报告": (book / "拆文报告.md").exists(),
        "必备文件文风": (book / "文风.md").exists(),
        "章节摘要存在": any((book / "章节").glob("*.md")) if (book / "章节").exists() else False,
        "角色档案存在": any((book / "角色").glob("*.md")) if (book / "角色").exists() else False,
        "设定目录存在": (book / "设定").exists(),
    }
    chapter_count = len(list((book / "章节").glob("*.md"))) if (book / "章节").exists() else 0
    ok = all(checks.values()) and chapter_count >= 50
    return {"pass": ok, "checks": checks, "chapter_count": chapter_count,
            "book_dir": str(book), "root": str(root)}


@router.get("/validate")
def validate_source(path: str = "") -> dict:
    target = _safe_dir(path)
    return _validate_chaishu(target)


class ImportIn(BaseModel):
    project_id: str
    source_path: str


@router.post("/import")
def import_teardown(body: ImportIn) -> dict:
    """拆书成果 → L1 提案区(source=import)+ 文风 → 风格指纹提案。"""
    root = _safe_dir(body.source_path)
    report = _validate_chaishu(root)
    if not report["pass"]:
        raise HTTPException(422, {"message": "收尾校验未通过", "report": report})

    book = Path(report["book_dir"])
    plans = _collect_import_plans(book)

    now = _now()
    created, per_cat = [], {}
    with tx() as conn:
        for cat, name, content in plans:
            eid = f"l1_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO l1_entries(id, project_id, category, name, fields, content,"
                " entry_status, source, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (eid, body.project_id, cat, name[:120], "{}", content,
                 "proposal", "import", now, now))
            created.append(eid)
            per_cat[cat] = per_cat.get(cat, 0) + 1
    return {"ok": True, "imported": len(created), "per_category": per_cat,
            "report": report}


# ── 拆书官 v2:整本 txt → 批量逐章拆解(断点续跑)──

import re as _re

CHAPTER_RE = _re.compile(r"^\s*(?:#{1,3}\s*)?第[零一二三四五六七八九十百千万\d]+章.*$", _re.M)


@router.get("/jobs")
def list_jobs(project_id: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM chaishu_jobs WHERE project_id=? ORDER BY created_at DESC",
            (project_id,)).fetchall()]
    for r in rows:
        r["chapters"] = json.loads(r.get("chapters") or "[]")
    return {"jobs": rows}


class JobIn(BaseModel):
    project_id: str
    book_title: str
    source_path: str
    batch_size: int = 50


@router.post("/job")
def create_job(body: JobIn) -> dict:
    """导入整本 txt:切分章节边界,建拆书任务(不调 LLM)。"""
    # S11(审计 2026-09-01):书名直接拼 output_dir,路径分隔符/相对引用/空名前置拒绝
    t = body.book_title
    if not t.strip() or "/" in t or "\\" in t or t.strip() in (".", ".."):
        raise HTTPException(422, "书名不能为空或含路径分隔符")
    source = Path(body.source_path)
    if not source.exists() or source.suffix.lower() not in (".txt", ".md"):
        raise HTTPException(422, "源文件不存在或不是 txt/md")
    text = source.read_text(encoding="utf-8", errors="ignore")
    matches = list(CHAPTER_RE.finditer(text))
    if not matches:
        raise HTTPException(422, "未识别到章节标题(需形如'第X章'的行)")
    chapters = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(0).strip().lstrip("#").strip()
        chapters.append({"n": i + 1, "title": title[:80], "start": m.start(), "end": end})
    out_dir = Path(__file__).resolve().parents[3] / "data" / "chaishu" / body.book_title
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "章节").mkdir(exist_ok=True)
    jid = f"job_{uuid.uuid4().hex[:20]}"
    now = _now()
    with tx() as conn:
        conn.execute(
            "INSERT INTO chaishu_jobs(id, project_id, book_title, source_path, output_dir,"
            " total_chapters, batch_size, chapters, stage, status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?, 'summaries', 'ready', ?, ?)",
            (jid, body.project_id, body.book_title, str(source), str(out_dir),
             len(chapters), body.batch_size, json.dumps(chapters, ensure_ascii=False), now, now))
        row = dict(conn.execute("SELECT * FROM chaishu_jobs WHERE id=?", (jid,)).fetchone())
    row["chapters"] = json.loads(row["chapters"])
    return {"ok": True, "job": row}


class RunIn(BaseModel):
    limit: int = 5   # 每次调用处理的章数(断点续跑,可反复点)


@router.post("/job/{jid}/run")
def run_job(jid: str, body: RunIn) -> dict:
    """跑下一批:逐章 LLM 摘要并落盘;每章即检查点,可随时中断续跑。"""
    with tx() as conn:
        job = dict(conn.execute("SELECT * FROM chaishu_jobs WHERE id=?", (jid,)).fetchone())
    if job is None:
        raise HTTPException(404, "任务不存在")
    # 单用户场景允许可重入:崩溃残留的 running 状态直接续跑
    chapters = json.loads(job["chapters"] or "[]")
    done = job["done_chapters"]
    source_text = Path(job["source_path"]).read_text(encoding="utf-8", errors="ignore")
    out_dir = Path(job["output_dir"])
    (out_dir / "章节").mkdir(parents=True, exist_ok=True)

    results = []
    target = min(done + max(1, body.limit), job["total_chapters"])
    with tx() as conn:
        conn.execute("UPDATE chaishu_jobs SET status='running', updated_at=? WHERE id=?",
                     (_now(), jid))
    for ch in chapters[done:target]:
        n, title = ch["n"], ch["title"]
        chunk = source_text[ch["start"]:ch["end"]][:16000]   # 16000:单章进摘要 prompt 的截断上限
        prompt = _prompt("拆书-章节摘要.md", {
            "{{CHAPTER_NUMBER}}": str(n), "{{CHAPTER_TITLE}}": title,
            "{{CHAPTER_TEXT}}": chunk,
        })
        prompt += touch_prompt_append("chaishu_summary")   # 批次六甲:触点追加
        try:
            r = chat_completion(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": "输出本章摘要 md。"}],
                action="chaishu_summary", project_id=job["project_id"],
                agent_type="chaishu", input_summary=f"拆书摘要:{job['book_title']} 第{n}章")
                # 上限=TOUCHES 登记 8000
            content = r["content"].strip()
        except Exception as exc:
            with tx() as conn:
                conn.execute("UPDATE chaishu_jobs SET status='paused', updated_at=? WHERE id=?",
                             (_now(), jid))
            raise HTTPException(502, f"第{n}章拆解失败:{str(exc)[:150]}(进度已保存,可重试续跑)")
        write_text_atomic(out_dir / "章节" / f"第{n}章_摘要.md", content)
        with tx() as conn:
            conn.execute("UPDATE chaishu_jobs SET done_chapters=?, updated_at=? WHERE id=?",
                         (done + 1, _now(), jid))
        done += 1
        results.append({"n": n, "title": title, "chars": len(content)})

    finished = done >= job["total_chapters"]
    with tx() as conn:
        conn.execute(
            "UPDATE chaishu_jobs SET status=?, updated_at=? WHERE id=?",
            ("done" if finished else "paused", _now(), jid))
    return {"ok": True, "processed": results, "done": done, "total": job["total_chapters"],
            "finished": finished, "output_dir": job["output_dir"]}


def _collect_import_plans(book: Path) -> list[tuple[str, str, str]]:
    """拆书成果 → (category, name, content) 收集(批次二:导入预览与导入共用)。"""
    plans: list[tuple[str, str, str]] = []
    for f in sorted((book / "角色").glob("*.md")):
        if f.name != "角色关系.md":
            plans.append(("character", f.stem, f.read_text(encoding="utf-8", errors="ignore")))
    for f in sorted((book / "设定" / "世界观").glob("*.md")):
        cat = next((c for key, c in CATEGORY_MAP if key in f.stem), "worldview")
        plans.append((cat, f.stem, f.read_text(encoding="utf-8", errors="ignore")))
    for f in sorted((book / "设定" / "势力").glob("*.md")):
        plans.append(("faction", f.stem, f.read_text(encoding="utf-8", errors="ignore")))
    for f in sorted((book / "设定").glob("*.md")):
        cat = next((c for key, c in CATEGORY_MAP if key in f.stem), None)
        if cat:
            plans.append((cat, f.stem, f.read_text(encoding="utf-8", errors="ignore")))
    style = book / "文风.md"
    if style.exists():
        plans.append(("style_fingerprint", "文风指纹(拆书)",
                      style.read_text(encoding="utf-8", errors="ignore")))
    return plans


class PreviewIn(BaseModel):
    source_path: str


@router.post("/import-preview")
def import_preview(body: PreviewIn) -> dict:
    """批次二 AI 流升级:导入前预览将创建的提案清单(不写库)。"""
    root = _safe_dir(body.source_path)
    report = _validate_chaishu(root)
    if not report["pass"]:
        raise HTTPException(422, {"message": "收尾校验未通过", "report": report})
    plans = _collect_import_plans(Path(report["book_dir"]))
    per_cat: dict[str, int] = {}
    for cat, _, _ in plans:
        per_cat[cat] = per_cat.get(cat, 0) + 1
    return {"count": len(plans), "per_category": per_cat,
            "names": [{"category": c, "name": n} for c, n, _ in plans]}


# ── 批次三①:文本导入(拆书官第二模式;执行书 §2①,2026-09-06)────────────────
# 纪要终拍:自有内容已排版不重排,纯算法识别既有结构(章节标记/MD 层级);
# 闸门不让路——L1 去向直接进既有提案区逐条批;大纲/正文去向=整批一条待批准提案
# (text_import_jobs),人看过逐章明细点一次批准才落库。

_CHAPTER_MARK = re.compile(r"^(?:#{1,4}\s+)?(第[0-9零一二两三四五六七八九十百千]+[章节回集].{0,40})$")
_MD_H1 = re.compile(r"^#\s+(.{1,60})$")
_OVERSIZE_CHARS = 20000  # 单节超 2 万字示警(疑似漏切)


def _split_text(text: str) -> tuple[list[dict], list[str]]:
    """纯算法切分:「第X章/节/回/集」行优先,Markdown 一级标题兜底,全无标记整篇单节。

    只识别既有结构,不重排不改写;返回(章节列表, 警示列表)。
    """
    warnings: list[str] = []
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return [], ["文本为空"]
    lines = text.split("\n")

    def _marks(pattern: re.Pattern[str]) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s and len(s) <= 60:
                m = pattern.match(s)
                if m:
                    out.append((i, (m.group(1) or s).strip()))
        return out

    marks = _marks(_CHAPTER_MARK)
    if not marks:
        marks = _marks(_MD_H1)
        if marks:
            warnings.append("未识别到「第X章」标记,已按 Markdown 一级标题切分")
    if not marks:
        warnings.append("未识别到任何章节标记,整篇作为单节导入(请人工复核切分)")
        return [{"index": 0, "title": text.split("\n", 1)[0][:60] or "全文",
                 "content": text, "chars": len(text)}], warnings

    if marks[0][0] > 0:
        preface = "\n".join(lines[:marks[0][0]]).strip()
        if preface:
            warnings.append(f"开头 {len(preface)} 字在首个章节标记前,未计入任何章(请人工处理)")
    chapters: list[dict] = []
    for idx, (start, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        if not body:
            continue  # 空节(连续标题/目录行)跳过
        chapters.append({"index": len(chapters), "title": title[:80],
                         "content": body, "chars": len(body)})
    oversize = [c["title"] for c in chapters if c["chars"] > _OVERSIZE_CHARS]
    if oversize:
        warnings.append(f"{len(oversize)} 节超 2 万字(疑似漏切,建议复核):"
                        + "、".join(oversize[:3]))
    return chapters, warnings


class TextSplitIn(BaseModel):
    text: str


@router.post("/text-split")
def text_split(body: TextSplitIn) -> dict:
    """纯算法切分预览,不写库(执行书 §2① 步骤 2/3)。"""
    chapters, warnings = _split_text(body.text)
    return {"chapters": chapters, "warnings": warnings,
            "total_chars": sum(c["chars"] for c in chapters)}


class TextImportIn(BaseModel):
    project_id: str
    text: str
    source_name: str = ""
    target: str = "outline"        # outline|manuscript|l1
    volume_id: str | None = None   # outline/manuscript 必填:章挂到该卷/近纲下


@router.post("/text-import")
def text_import(body: TextImportIn) -> dict:
    """提交导入:l1=直接写 l1_entries 提案(既有提案区闸门,逐条批准);
    outline/manuscript=整批一条待批准提案(text_import_jobs),批准端点才落库。"""
    if body.target not in ("outline", "manuscript", "l1"):
        raise HTTPException(422, f"未知去向 {body.target}")
    chapters, warnings = _split_text(body.text)
    if not chapters:
        raise HTTPException(422, "文本为空")
    now = _now()
    if body.target == "l1":
        with tx() as conn:
            if not conn.execute("SELECT 1 FROM projects WHERE id=?",
                                (body.project_id,)).fetchone():
                raise HTTPException(404, "项目不存在")
            ids = []
            for c in chapters:
                eid = f"l1_{uuid.uuid4().hex[:20]}"
                conn.execute(
                    "INSERT INTO l1_entries(id, project_id, category, name, content,"
                    " entry_status, source, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (eid, body.project_id, "worldview", c["title"],
                     c["content"][:8000], "proposal", "import", now, now))
                ids.append(eid)
        return {"mode": "l1", "count": len(ids), "message":
                f"已入提案区 {len(ids)} 条(去 L1 档案库逐条批准)"}
    if not body.volume_id:
        raise HTTPException(422, "该去向需先选择目标卷/近纲")
    with tx() as conn:
        vol = conn.execute(
            "SELECT kind FROM outline_nodes WHERE id=? AND project_id=?",
            (body.volume_id, body.project_id)).fetchone()
        if not vol or vol["kind"] not in ("volume", "arc"):
            raise HTTPException(422, "目标卷不存在或类型不符(须为卷/近纲)")
        jid = f"tij_{uuid.uuid4().hex[:20]}"
        conn.execute(
            "INSERT INTO text_import_jobs(id, project_id, source_name, target,"
            " volume_id, chapters, warnings, status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (jid, body.project_id, body.source_name, body.target, body.volume_id,
             json.dumps(chapters, ensure_ascii=False),
             json.dumps(warnings, ensure_ascii=False),
             "awaiting_approval", now, now))
    return {"mode": body.target, "job_id": jid, "count": len(chapters),
            "message": f"已提请导入 {len(chapters)} 章(整批一条提案,批准后落"
                       f"{'正文' if body.target == 'manuscript' else '大纲'})"}


@router.get("/text-imports")
def text_imports(project_id: str) -> dict:
    with tx() as conn:
        rows = conn.execute(
            "SELECT id, source_name, target, volume_id, chapters, warnings, status,"
            " created_at FROM text_import_jobs WHERE project_id=?"
            " ORDER BY created_at DESC LIMIT 20", (project_id,)).fetchall()
    jobs = []
    for r in rows:
        chapters = json.loads(r["chapters"] or "[]")
        jobs.append({"id": r["id"], "source_name": r["source_name"],
                     "target": r["target"], "volume_id": r["volume_id"],
                     "status": r["status"], "created_at": r["created_at"],
                     "count": len(chapters),
                     "titles": [c["title"] for c in chapters[:8]],
                     "warnings": json.loads(r["warnings"] or "[]")})
    return {"jobs": jobs}


class OrganizeIn(BaseModel):
    text: str
    instruction: str = ""     # 可选:整理侧重(如"去口语化"),空=默认顺句规整


@router.post("/text-organize")
def text_organize(body: OrganizeIn) -> dict:
    """AI 整理官(批次三①,执行书:可选**默认关**)——对切分后的单节出整理建议。

    定位=只服务第三方拆书内容(自有内容已排版不重排,终拍口径);开关=前端显式
    勾选才调用,后端双重校验 settings.ui.organizer_enabled(默认 False)。
    返回建议文本(不直接改原文),人对比后自行采用——闸门纪律。"""
    if not get_settings().get("ui", {}).get("organizer_enabled"):
        raise HTTPException(403, "AI 整理官未开启(设置页「界面」组勾选后可用;自有内容不建议重排)")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "文本为空")
    prompt = ("你是文本整理助手。对以下内容做轻整理(顺句/去重复/标点规整),"
              "不改变事实与结构,输出整理后全文。"
              + (f"整理侧重:{body.instruction}。" if body.instruction else "")
              + chr(10) * 2 + "原文:" + chr(10) + text[:6000])
    prompt += touch_prompt_append("chaishu_organize")   # 批次六甲:触点追加(整形指令后)
    r = chat_completion([{"role": "user", "content": prompt}], action="chaishu_organize",
                        project_id=None, agent_type="chaishu",
                        input_summary=f"整理官:{body.instruction or '默认'}",
                        max_tokens_override=8000)
    return {"suggestion": r["content"], "cost": r["usage"]["cost_total"],
            "model": r["model"], "usage": r["usage"]}


class TextImportApproveIn(BaseModel):
    volume_id: str | None = None   # 缺省用提案里的目标卷;可在此改挂


@router.post("/text-imports/{jid}/approve")
def text_import_approve(jid: str, body: TextImportApproveIn) -> dict:
    """批准整批:outline=批量建章(unwritten);manuscript=建章+每章正文落 l4(draft)。"""
    now = _now()
    with tx() as conn:
        job = conn.execute("SELECT * FROM text_import_jobs WHERE id=?", (jid,)).fetchone()
        if not job:
            raise HTTPException(404, "导入提案不存在")
        if job["status"] != "awaiting_approval":
            raise HTTPException(409, f"该提案已处理({job['status']})")
        volume_id = body.volume_id or job["volume_id"]
        vol = conn.execute(
            "SELECT kind FROM outline_nodes WHERE id=? AND project_id=?",
            (volume_id, job["project_id"])).fetchone()
        if not vol or vol["kind"] not in ("volume", "arc"):
            raise HTTPException(422, "目标卷不存在或类型不符")
        chapters = json.loads(job["chapters"] or "[]")
        node_ids: list[str] = []
        for c in chapters:
            nid = f"on_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
                " sort_order, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (nid, job["project_id"], volume_id, "chapter", c["title"][:80],
                 c["index"], "draft" if job["target"] == "manuscript" else "unwritten",
                 now, now))
            node_ids.append(nid)
            if job["target"] == "manuscript":
                conn.execute(
                    "INSERT INTO l4_texts(node_id, content, md_path, updated_at)"
                    " VALUES(?,?,NULL,?)", (nid, c["content"], now))
        conn.execute(
            "UPDATE text_import_jobs SET status='approved', volume_id=?,"
            " decided_at=?, updated_at=? WHERE id=?", (volume_id, now, now, jid))
    return {"ok": True, "created": len(node_ids), "node_ids": node_ids}


@router.post("/text-imports/{jid}/reject")
def text_import_reject(jid: str) -> dict:
    with tx() as conn:
        cur = conn.execute(
            "UPDATE text_import_jobs SET status='rejected', decided_at=?,"
            " updated_at=? WHERE id=? AND status='awaiting_approval'",
            (_now(), _now(), jid))
        if cur.rowcount == 0:
            raise HTTPException(409, "提案不存在或已处理")
    return {"ok": True}


# MCP 查证域(mcp/status / verify / evidence)自 chaishu_verify.py 子路由挂载:
# 同前缀 /api/chaishu,路径与本文件各端点无重叠,注册顺序对外零变化。
router.include_router(verify_router)