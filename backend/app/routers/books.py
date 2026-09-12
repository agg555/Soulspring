"""书籍工作区 API(M2):书籍详情/编辑 + F0 向导选项字典。

向导字典来自 app/f0_options.json(gen_f0_options.py 从云笔数据生成),
前端不硬编码字典。总览页 = 唯一入口:书架 → 点书进入工作区(子页签明确分区)。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from urllib.parse import quote

from ..db import tx
from ..mirror import build_mirror
from ..settings_store import get_settings, resolve_skill, update_settings

router = APIRouter(prefix="/api/books", tags=["books"])

OPTIONS_PATH = Path(__file__).resolve().parent.parent / "f0_options.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "l1_schema.json"

# 向导字段白名单:允许通过 PUT 更新的列(其余列代码层不可达)
WIZARD_FIELDS = [
    "name", "genre", "description", "protagonist", "tropes", "audience",
    "style", "plot_mode", "power_preset", "cheat_preset",
    "core_conflict", "chapter_words", "target_words",
]
LIST_FIELDS = {"tropes", "style"}  # 多选字段,存 JSON 数组


@router.get("/options")
def options() -> dict:
    return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))


@router.get("/l1-schema")
def l1_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_book(conn, pid: str) -> dict:
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "书不存在")
    book = dict(row)
    for k in LIST_FIELDS:
        try:
            book[k] = json.loads(book.get(k) or "[]")
        except (json.JSONDecodeError, TypeError):
            book[k] = []
    return book


@router.get("/{pid}")
def book_detail(pid: str) -> dict:
    with tx() as conn:
        book = _load_book(conn, pid)
        l1_rows = conn.execute(
            "SELECT category, entry_status, COUNT(*) n FROM l1_entries"
            " WHERE project_id=? GROUP BY category, entry_status", (pid,)).fetchall()
        outline = conn.execute(
            "SELECT kind, COUNT(*) n FROM outline_nodes WHERE project_id=?"
            " GROUP BY kind", (pid,)).fetchall()
    skills_cfg = get_settings()["skills"]
    counts: dict[str, dict[str, int]] = {}
    for r in l1_rows:
        counts.setdefault(r["category"], {})[r["entry_status"]] = r["n"]
    return {
        "book": book,
        "l1_counts": counts,
        "outline_counts": {r["kind"]: r["n"] for r in outline},
        # 单本书技能(需求3):override=null 表示跟随全局;" "=该书强制不启用
        "skill_override": (skills_cfg.get("book_overrides") or {}).get(pid),
        "skill_global": skills_cfg.get("global_default") or "",
        "skill_effective": resolve_skill(pid),
    }


@router.put("/{pid}")
def update_book(pid: str, patch: dict) -> dict:
    # 单本书技能覆盖(需求3):优先级 单本书 > 全局 > 不启用;存 settings KV 不动表
    if "skill_override" in patch:
        val = patch.pop("skill_override")
        if val not in (None, "") and not isinstance(val, str):
            raise HTTPException(422, "skill_override 应为技能目录名、空串(不启用)或 null(跟随全局)")
        overrides = dict(get_settings()["skills"].get("book_overrides") or {})
        if val is None:
            overrides.pop(pid, None)      # 跟随全局 = 移除覆盖
        else:
            overrides[pid] = val.strip()
        update_settings("skills", {"book_overrides": overrides})

    updates = {}
    for k in WIZARD_FIELDS:
        if k not in patch:
            continue
        v = patch[k]
        if k in LIST_FIELDS:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise HTTPException(422, f"{k} 应为字符串数组")
            updates[k] = json.dumps(v, ensure_ascii=False)
        elif k in ("chapter_words", "target_words"):
            updates[k] = int(v) if v not in (None, "") else None
        else:
            updates[k] = str(v).strip() if isinstance(v, str) else v
    if "name" in updates and not updates["name"]:
        raise HTTPException(422, "书名不能为空")
    if not updates and "skill_override" not in patch:
        raise HTTPException(422, "无可更新字段")
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k}=?" for k in updates)
        with tx() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
                raise HTTPException(404, "书不存在")
            conn.execute(f"UPDATE projects SET {sets} WHERE id=?", (*updates.values(), pid))
            book = _load_book(conn, pid)
    else:
        with tx() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
                raise HTTPException(404, "书不存在")
            book = _load_book(conn, pid)
    return {"ok": True, "book": book}


@router.get("/{pid}/export")
def export_book(pid: str, fmt: str = "md") -> Response:
    """全书正文导出(用户拍板 2026-09-06:txt/md 两种)。

    按章节创建序组织;只收正文非空(l4)的章;md=# 标题,txt=纯标题行。
    候选清单落地批(2026-09-10):md 随章节卡四行(摘要/备注/关联事件/登场人物);
    txt 维持纯正文(阅读器场景)。
    """
    fmt = fmt.lower()
    if fmt not in ("txt", "md"):
        raise HTTPException(422, "fmt 仅支持 txt/md")
    from .chapter_card import _cast_nodes, chapter_no
    with tx() as conn:
        book = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()
        if not book:
            raise HTTPException(404, "书不存在")
        rows = conn.execute(
            "SELECT n.id, n.title, n.summary, n.note, t.content FROM outline_nodes n"
            " JOIN l4_texts t ON t.node_id = n.id"
            " WHERE n.project_id=? AND n.kind='chapter' AND TRIM(t.content)<>''"
            " ORDER BY n.created_at, n.id", (pid,)).fetchall()
        events_by_node: dict[str, list[str]] = {}
        for r in conn.execute(
                "SELECT ec.node_id, e.title FROM event_chapters ec"
                " JOIN timeline_events e ON e.id = ec.event_id"
                " WHERE e.project_id=?", (pid,)).fetchall():
            events_by_node.setdefault(r["node_id"], []).append(r["title"])
        char_by_id = {r["id"]: r["label"] for r in conn.execute(
            "SELECT n.id, n.label FROM graph_nodes n"
            " JOIN graph_boards b ON b.id = n.board_id"
            " WHERE b.project_id=? AND b.kind='character'", (pid,)).fetchall()}
        cast_labels: dict[str, list[str]] = {}
        for r in rows:
            no = chapter_no(r["title"])
            if no is not None:
                cast_labels[r["id"]] = sorted(
                    char_by_id[nid] for nid in _cast_nodes(conn, pid, no)
                    if nid in char_by_id)
    name = book["name"]
    parts = []
    for r in rows:
        head = (f"# {r['title'].strip()}" if fmt == "md" else r["title"].strip())
        piece = head + f"\n\n{r['content'].strip()}"
        if fmt == "md" and (r["summary"] or r["note"]
                            or events_by_node.get(r["id"]) or cast_labels.get(r["id"])):
            lines = []
            if r["summary"]:
                lines.append(f"> 摘要:{r['summary']}")
            if r["note"]:
                lines.append(f"> 备注:{r['note']}")
            if events_by_node.get(r["id"]):
                lines.append("> 关联事件:" + "、".join(events_by_node[r["id"]]))
            if cast_labels.get(r["id"]):
                lines.append("> 登场人物:" + "、".join(cast_labels[r["id"]]))
            piece += "\n\n" + "\n".join(lines)
        parts.append(piece)
    text = (f"《{name}》\n\n" + "\n\n".join(parts)) if parts else f"《{name}》(暂无章节正文)"
    return Response(
        text, media_type=f"text/{'markdown' if fmt == 'md' else 'plain'}; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(name + '.' + fmt)}"})


@router.get("/{pid}/reading")
def reading_list(pid: str, mode: str = "all") -> dict:
    """阅读模式数据源(候选清单落地批 B):有正文的章,创建序;mode=finalized 只回定稿。"""
    if mode not in ("all", "finalized"):
        raise HTTPException(422, "mode 仅支持 all/finalized")
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        book = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()
        extra = " AND n.status='finalized'" if mode == "finalized" else ""
        rows = conn.execute(
            "SELECT n.id, n.title, n.status, t.content FROM outline_nodes n"
            " JOIN l4_texts t ON t.node_id = n.id"
            " WHERE n.project_id=? AND n.kind='chapter' AND TRIM(t.content)<>''" + extra +
            " ORDER BY n.created_at, n.id", (pid,)).fetchall()
    return {"book_name": book["name"] if book else "",
            "chapters": [dict(r) for r in rows]}


@router.post("/{pid}/mirror")
def mirror_book(pid: str) -> dict:
    """批次四③:全书 md 镜像重建(data/books/<书名>/;DB 唯一真源,md 只读)。"""
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        result = build_mirror(conn, pid)
    return {"ok": True, **result}


@router.post("/{pid}/open-folder")
def open_folder(pid: str) -> dict:
    """打开镜像书目录(资源管理器;目录未生成则提示先同步)。仅本机单用户语义。"""
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        name = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()["name"]
    from ..mirror import _DATA_DIR, _safe_name
    path = _DATA_DIR / "books" / _safe_name(name)
    if not path.is_dir():
        raise HTTPException(404, "书目录尚未生成:请先点「同步书目录」")
    import os
    os.startfile(str(path))  # noqa: S606 — Windows 本机单用户,打开资源管理器
    return {"ok": True, "dir": str(path)}
