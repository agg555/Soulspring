"""C4 分支探索 API(S1 三拆自 conversations.py,纯移动零行为变化)。

分支 = 一条特殊会话(conversation_sessions.owner_type='branch')+ 节点字段草稿包;
改草稿主干不动,作者确认[转正]后逐字段 diff 写回主干并留版本历史。
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

BRANCH_FIELDS = ("title", "summary", "note", "scene_fields")   # 分支草稿可动的字段


def _branch_snapshot(node) -> dict:
    """主干字段快照 → 分支初始草稿(scene 节点附五字段对象)。"""
    snap = {"title": node["title"], "summary": node["summary"] or "",
            "note": node["note"] or ""}
    if node["kind"] == "scene":
        try:
            snap["scene_fields"] = json.loads(node["scene_fields"] or "{}")
        except json.JSONDecodeError:
            snap["scene_fields"] = {}
    return snap


def _branch_view(row: dict) -> dict:
    out = dict(row)
    try:
        out["branch_payload"] = json.loads(out.get("branch_payload") or "{}")
    except json.JSONDecodeError:
        out["branch_payload"] = {}
    return out


class BranchIn(BaseModel):
    node_id: str
    name: str


@router.post("/branches", status_code=201)
def create_branch(body: BranchIn) -> dict:
    """命名附属分支:分支 = conversation_sessions(owner_type='branch') + 字段草稿副本。"""
    if not body.name.strip():
        raise HTTPException(422, "分支名不能为空")
    with tx() as conn:
        node = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (body.node_id,)).fetchone()
        if node is None:
            raise HTTPException(404, "节点不存在")
        if node["kind"] not in ("chapter", "scene"):
            raise HTTPException(422, "只有章/场景节点可以开分支探索")
        sid = f"conv_{uuid.uuid4().hex[:20]}"
        conn.execute(
            "INSERT INTO conversation_sessions(id, project_id, owner_type, owner_id, name,"
            " branch_payload, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, node["project_id"], "branch", body.node_id, body.name.strip(),
             json.dumps(_branch_snapshot(node), ensure_ascii=False), "active", _now()))
        row = dict(conn.execute("SELECT * FROM conversation_sessions WHERE id=?", (sid,)).fetchone())
    return {"branch": _branch_view(row)}


@router.get("/branches")
def list_branches(node_id: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, status, branch_payload, created_at FROM conversation_sessions"
            " WHERE owner_type='branch' AND owner_id=? ORDER BY created_at", (node_id,)).fetchall()]
    return {"branches": [_branch_view(r) for r in rows]}


class BranchPayloadIn(BaseModel):
    payload: dict


@router.put("/branches/{sid}/payload")
def put_branch_payload(sid: str, body: BranchPayloadIn) -> dict:
    """改分支草稿(白名单字段;主干纹丝不动;已结案的分支拒绝再改)。"""
    clean = {}
    for k in BRANCH_FIELDS:
        if k not in body.payload:
            continue
        if k == "scene_fields":
            clean[k] = body.payload[k] if isinstance(body.payload[k], dict) else {}
        else:
            clean[k] = str(body.payload[k] or "")
    if "title" in clean and not clean["title"].strip():
        raise HTTPException(422, "草稿标题不能为空")
    if not clean:
        raise HTTPException(422, "无可更新的草稿字段")
    with tx() as conn:
        row = conn.execute(
            "SELECT * FROM conversation_sessions WHERE id=? AND owner_type='branch'",
            (sid,)).fetchone()
        if row is None:
            raise HTTPException(404, "分支不存在")
        if row["status"] != "active":
            raise HTTPException(409, "分支已结案(转正/归档),不能再改草稿")
        payload = _branch_view(row)["branch_payload"]
        payload.update(clean)
        conn.execute("UPDATE conversation_sessions SET branch_payload=? WHERE id=?",
                     (json.dumps(payload, ensure_ascii=False), sid))
        fresh = dict(conn.execute("SELECT * FROM conversation_sessions WHERE id=?", (sid,)).fetchone())
    return {"ok": True, "branch": _branch_view(fresh)}


@router.post("/branches/{sid}/promote")
def promote_branch(sid: str) -> dict:
    """转正:逐字段 diff 写回主干(前端弹 diff 人已确认);原值进 outline_field_history。"""
    with tx() as conn:
        branch = conn.execute(
            "SELECT * FROM conversation_sessions WHERE id=? AND owner_type='branch'",
            (sid,)).fetchone()
        if branch is None:
            raise HTTPException(404, "分支不存在")
        if branch["status"] != "active":
            raise HTTPException(409, "分支已结案,不能重复转正")
        node = conn.execute(
            "SELECT * FROM outline_nodes WHERE id=?", (branch["owner_id"],)).fetchone()
        if node is None:
            raise HTTPException(404, "主干节点不存在")
        payload = _branch_view(branch)["branch_payload"]
        now = _now()
        applied = []
        for field in BRANCH_FIELDS:
            if field not in payload:
                continue
            if field == "scene_fields":
                if node["kind"] != "scene":
                    continue
                old_val = node["scene_fields"] or "{}"
                new_val = json.dumps(payload[field] or {}, ensure_ascii=False)
            else:
                old_val = node[field] or ""
                new_val = str(payload[field] or "")
                if field == "title" and not new_val.strip():
                    continue   # 标题不回写空值
            if new_val == old_val:
                continue
            conn.execute(
                f"UPDATE outline_nodes SET {field}=? WHERE id=?", (new_val, node["id"]))
            conn.execute(
                "INSERT INTO outline_field_history(id, node_id, field, before, after,"
                " source, session_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"fh_{uuid.uuid4().hex[:20]}", node["id"], field, old_val, new_val,
                 "branch_promote", sid, now))
            applied.append({"field": field, "before": old_val, "after": new_val})
        if applied:
            conn.execute("UPDATE outline_nodes SET updated_at=? WHERE id=?", (now, node["id"]))
        conn.execute("UPDATE conversation_sessions SET status='archived' WHERE id=?", (sid,))
    return {"ok": True, "applied": applied, "branch_status": "archived"}


@router.post("/branches/{sid}/archive")
def archive_branch(sid: str) -> dict:
    """归档:分支结案,草稿保留在会话里可回看,不再参与转正。"""
    with tx() as conn:
        row = conn.execute(
            "SELECT id FROM conversation_sessions WHERE id=? AND owner_type='branch'",
            (sid,)).fetchone()
        if row is None:
            raise HTTPException(404, "分支不存在")
        conn.execute("UPDATE conversation_sessions SET status='archived' WHERE id=?", (sid,))
    return {"ok": True, "status": "archived"}
