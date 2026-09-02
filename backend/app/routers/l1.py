"""L1 档案库 API(M2):六类档案 + 提案批准流 + 风格指纹只读。

写入协议落地(任务书 §4.2,系统级拒绝):
- AI 产出的条目只能走 ai_proposals 入口,服务端强制 entry_status='proposal'、
  source='ai_proposal'——代码层不存在"AI 直接写正式区"的接口;
- 风格指纹是 L1 特殊区,唯一写入者是蒸馏管道(M5+),本模块一切写路径对它 403。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx

router = APIRouter(prefix="/api", tags=["l1"])

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "l1_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
CATEGORIES = {c["key"]: c for c in SCHEMA["categories"]}
STYLE_FINGERPRINT = "style_fingerprint"  # 特殊区,不在六类表单里
VALID_CATEGORIES = set(CATEGORIES) | {STYLE_FINGERPRINT}


def _check_fields(category: str, fields: Any) -> dict:
    if not isinstance(fields, dict):
        raise HTTPException(422, "fields 应为对象")
    allowed = {f["key"] for f in CATEGORIES[category]["fields"]} if category in CATEGORIES else set()
    out = {k: str(v) for k, v in fields.items() if k in allowed and str(v).strip()}
    return out


def _entry_row(row) -> dict:
    d = dict(row)
    try:
        d["fields"] = json.loads(d.get("fields") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["fields"] = {}
    return d


@router.get("/books/{pid}/l1")
def list_entries(pid: str) -> dict:
    with tx() as conn:
        rows = conn.execute(
            "SELECT * FROM l1_entries WHERE project_id=?"
            " ORDER BY category, entry_status DESC, updated_at DESC", (pid,)).fetchall()
    entries = [_entry_row(r) for r in rows]
    return {
        "entries": entries,
        "style_fingerprint": [e for e in entries if e["category"] == STYLE_FINGERPRINT],
    }


class EntryIn(BaseModel):
    category: str
    name: str
    fields: dict = {}
    notes: str = ""


@router.post("/books/{pid}/l1", status_code=201)
def create_entry(pid: str, body: EntryIn) -> dict:
    """人手工建档:直接入正式区(source=manual)。"""
    if body.category not in CATEGORIES:
        if body.category == STYLE_FINGERPRINT:
            raise HTTPException(403, "风格指纹由蒸馏管道独占写入,不开放手工建档")
        raise HTTPException(422, f"未知档案类别: {body.category}")
    if not body.name.strip():
        raise HTTPException(422, "条目名称不能为空")
    now = _now()
    eid = f"l1_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, fields, content,"
            " entry_status, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (eid, pid, body.category, body.name.strip(),
             json.dumps(_check_fields(body.category, body.fields), ensure_ascii=False),
             body.notes, "confirmed", "manual", now, now),
        )
    return {"id": eid, "entry_status": "confirmed"}


@router.post("/books/{pid}/l1/ai-proposals", status_code=201)
def create_ai_proposals(pid: str, proposals: list[EntryIn]) -> dict:
    """AI 构建管道专用入口:无论调用方传什么,一律强制落提案区(写入协议)。"""
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        created = []
        now = _now()
        for p in proposals:
            if p.category not in CATEGORIES:  # 含风格指纹:AI 也不许碰
                continue
            if not p.name.strip():
                continue
            eid = f"l1_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO l1_entries(id, project_id, category, name, fields, content,"
                " entry_status, source, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (eid, pid, p.category, p.name.strip(),
                 json.dumps(_check_fields(p.category, p.fields), ensure_ascii=False),
                 p.notes, "proposal", "ai_proposal", now, now),
            )
            created.append(eid)
    return {"created": created, "count": len(created)}


@router.put("/l1/{eid}")
def update_entry(eid: str, patch: dict) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM l1_entries WHERE id=?", (eid,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        entry = dict(row)
        if entry["category"] == STYLE_FINGERPRINT:
            raise HTTPException(403, "风格指纹由蒸馏管道独占写入")
        name = str(patch.get("name", entry["name"])).strip()
        if not name:
            raise HTTPException(422, "条目名称不能为空")
        fields = _check_fields(entry["category"], patch.get("fields", json.loads(entry["fields"])))
        notes = str(patch.get("notes", entry["content"]))
        # 人手工编辑不改变状态与来源:提案被编辑后仍是提案,批准流程不变
        conn.execute(
            "UPDATE l1_entries SET name=?, fields=?, content=?, updated_at=? WHERE id=?",
            (name, json.dumps(fields, ensure_ascii=False), notes, _now(), eid),
        )
        fresh = conn.execute("SELECT * FROM l1_entries WHERE id=?", (eid,)).fetchone()
    return _entry_row(fresh)


@router.post("/l1/{eid}/approve")
def approve_entry(eid: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM l1_entries WHERE id=?", (eid,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        if row["entry_status"] == "confirmed":
            return {"ok": True, "entry_status": "confirmed", "note": "已是正式条目"}
        conn.execute(
            "UPDATE l1_entries SET entry_status='confirmed', updated_at=? WHERE id=?",
            (_now(), eid),
        )
    return {"ok": True, "entry_status": "confirmed"}


@router.put("/l1/{eid}/presence")
def set_presence(eid: str, body: PresenceIn) -> dict:
    """常驻/按需标记:常驻条目每章装配必带,按需条目按计划卡匹配。"""
    if body.presence not in ("always", "on_demand"):
        raise HTTPException(422, "presence 只能是 always/on_demand")
    with tx() as conn:
        row = conn.execute("SELECT category FROM l1_entries WHERE id=?", (eid,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        if row["category"] == STYLE_FINGERPRINT:
            raise HTTPException(403, "风格指纹由蒸馏管道独占管理")
        conn.execute("UPDATE l1_entries SET presence=?, updated_at=? WHERE id=?",
                     (body.presence, _now(), eid))
    return {"ok": True, "presence": body.presence}


class PresenceIn(BaseModel):
    presence: str


@router.delete("/l1/{eid}")
def delete_entry(eid: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM l1_entries WHERE id=?", (eid,)).fetchone()
        if row is None:
            raise HTTPException(404, "条目不存在")
        if row["category"] == STYLE_FINGERPRINT:
            raise HTTPException(403, "风格指纹由蒸馏管道独占管理")
        conn.execute("DELETE FROM l1_entries WHERE id=?", (eid,))
        # 角色条目删除时同步清角色关系(判据:删角色后图与关系表一致)
        conn.execute(
            "DELETE FROM character_relations WHERE from_entry_id=? OR to_entry_id=?",
            (eid, eid))
        # 统一图谱引擎(v11):清 ref 指向该条目的节点与相连边
        graph_nids = [r["id"] for r in conn.execute(
            "SELECT id FROM graph_nodes WHERE ref_type='l1_entry' AND ref_id=?", (eid,)).fetchall()]
        if graph_nids:
            marks = ",".join("?" for _ in graph_nids)
            conn.execute(
                f"DELETE FROM graph_edges WHERE from_node_id IN ({marks})"
                f" OR to_node_id IN ({marks})", (*graph_nids, *graph_nids))
            conn.execute(f"DELETE FROM graph_nodes WHERE id IN ({marks})", graph_nids)
    return {"ok": True}
