"""书籍工作区 API(M2):书籍详情/编辑 + F0 向导选项字典。

向导字典来自 app/f0_options.json(gen_f0_options.py 从云笔数据生成),
前端不硬编码字典。总览页 = 唯一入口:书架 → 点书进入工作区(子页签明确分区)。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..db import tx

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
    from ..settings_store import get_settings, resolve_skill
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
        from ..settings_store import get_settings, update_settings
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
