"""拆书官平移(F11)+ 素材库挂载 + MCP 查证(F12)。

- 拆书导入:旧系统拆书成果(17 维度目录树)→ 映射到 L1 六类提案区(source=import);
  文风.md → 风格指纹提案(蒸馏管道产物,人批准生效);
  收尾校验 = 旧系统 check-chaishu.js 的等价物(必备文件/设定完整性/章节覆盖)。
- 素材库只读浏览 + 标记进装配池(= 导入为 L1 提案)。
- 查证:MCP 官方 SDK stdio 白名单制,wiki 优先、tavily 降级(旧系统纪律);
  取证落素材库(来源/时间/置信度)。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now, _prompt
from ..db import tx
from ..ledger.usage import chat_completion
from ..llm.atomic_io import write_text_atomic
from ..settings_store import get_settings

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
    plans: list[tuple[str, str, str]] = []  # (category, name, content)

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
        plans.append(("style_fingerprint", "文风指纹(拆书)", style.read_text(encoding="utf-8", errors="ignore")))

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


# ── MCP 查证(F12)──

@router.get("/mcp/status")
def mcp_status() -> dict:
    mcp = get_settings()["mcp"]
    key_ok = "tavily_api_key" in _secrets()
    return {"whitelist": mcp.get("servers", []), "fallback": mcp.get("search_fallback"),
            "tavily_key_configured": key_ok}


def _secrets() -> dict:
    from ..settings_store import SECRETS_PATH
    if not SECRETS_PATH.exists():
        return {}
    return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """tavily 降级通道(旧系统纪律);HTTP API 直连。"""
    import urllib.request

    key = _secrets().get("tavily_api_key", "")
    if not key:
        raise HTTPException(409, "未配置 tavily key(设置页/素材库降级不可用)")
    payload = json.dumps({"api_key": key, "query": query, "max_results": max_results,
                          "search_depth": "basic"}).encode()
    req = urllib.request.Request("https://api.tavily.com/search", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "content": (x.get("content") or "")[:800],
             "confidence": x.get("score", 0.5)} for x in data.get("results", [])]


def _wiki_mcp_search(query: str, lang: str) -> list[dict]:
    """MCP 基座:官方 SDK stdio 白名单制调用。"""
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = next((s for s in get_settings()["mcp"]["servers"]
                   if s["name"] == f"wiki-{lang}"), None)
    if server is None:
        raise HTTPException(403, f"服务端 {lang} 不在白名单内")
    command = str((Path(__file__).resolve().parent.parent / ".venv" / "Scripts" /
                   f"{server['command']}.exe").resolve())

    async def run() -> list[dict]:
        params = StdioServerParameters(command=command, args=server["args"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("search_wikipedia",
                                            {"query": query, "limit": 5})
                for c in r.content:
                    t = getattr(c, "text", None)
                    if t:
                        try:
                            data = json.loads(t)
                            return [{"title": x.get("title", ""), "url": x.get("url", ""),
                                     "content": (x.get("snippet") or x.get("extract") or "")[:800],
                                     "confidence": 0.7} for x in data.get("results", [])]
                        except json.JSONDecodeError:
                            continue
                return []

    return asyncio.run(run())


class VerifyIn(BaseModel):
    project_id: str
    query: str
    lang: str = "zh"


@router.post("/verify")
def verify(body: VerifyIn) -> dict:
    """查证:wiki 优先 → tavily 降级 → 结果落素材库(来源/时间/置信度)。"""
    t0 = time.monotonic()
    results, via = [], ""
    try:
        results = _wiki_mcp_search(body.query, body.lang)
        via = f"wiki-{body.lang}"
    except HTTPException:
        raise
    except Exception:
        results = []
    if not results:
        results = _tavily_search(body.query)
        via = "tavily"
    duration_ms = int((time.monotonic() - t0) * 1000)
    saved = []
    with tx() as conn:
        for x in results:
            eid = f"ev_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO evidence_items(id, project_id, query, source, url, content,"
                " confidence, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (eid, body.project_id, body.query, via, x.get("url", ""),
                 x.get("content", ""), x.get("confidence", 0.5), _now()))
            saved.append(eid)
    return {"ok": True, "via": via, "count": len(saved), "duration_ms": duration_ms,
            "results": results}


@router.get("/evidence")
def evidence_list(project_id: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT query, source, url, content, confidence, created_at FROM evidence_items"
            " WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,)).fetchall()]
    return {"evidence": rows}


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
        try:
            r = chat_completion(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": "输出本章摘要 md。"}],
                action="chaishu_summary", project_id=job["project_id"],
                agent_type="chaishu", input_summary=f"拆书摘要:{job['book_title']} 第{n}章",
                max_tokens_override=8000)
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
