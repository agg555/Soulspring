"""构思树 API(批次七⑤,执行书附节六节方案 2026-09-08 用户审通过)。

- 建议块/奇思妙想「下钻」与手动「+子构思」都落 idea_nodes;子讨论=
  conversation_sessions.owner_type='idea'(见 conversations.py _context_idea:
  父链层叠摘要进 system,复用批次三⑤ digest 纯算法);
- 三态:open 待议 / adopted 采纳(**标记共识达成;真正的数据写回仍只能走
  conversations 建议采纳闸门 adopt.py——本路由不提供任何写大纲/正文/图谱的
  通道,判据"转正写回走闸门"由架构保证**)/ dropped 放弃(冻结:链上任一
  dropped 即整线不喂 AI,可回待议解冻);
- 深度≤3(根=1);删构思级联删整棵子树。
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx

router = APIRouter(prefix="/api/ideas", tags=["ideas"])

MAX_DEPTH = 3
IDEA_STATUSES = ("open", "adopted", "dropped")


def _get_idea(conn, iid: str) -> dict:
    row = conn.execute("SELECT * FROM idea_nodes WHERE id=?", (iid,)).fetchone()
    if row is None:
        raise HTTPException(404, "构思不存在")
    return dict(row)


def _chain(conn, idea: dict) -> list[dict]:
    """父链:从根到自身(含自身)。"""
    chain = [idea]
    cur = idea
    while cur["parent_idea_id"]:
        cur = _get_idea(conn, cur["parent_idea_id"])
        chain.append(cur)
    chain.reverse()
    return chain


def _view(row: dict) -> dict:
    out = dict(row)
    if out.get("source_ref"):
        try:
            out["source_ref"] = json.loads(out["source_ref"])
        except json.JSONDecodeError:
            out["source_ref"] = None
    return out


class IdeaIn(BaseModel):
    pid: str
    title: str
    note: str = ""
    parent_idea_id: str | None = None
    source_ref: dict | None = None    # {session_id, message_id, idx} 下钻来源


@router.get("")
def list_ideas(pid: str) -> dict:
    """全书构思平铺(前端按 parent_idea_id 组树);含每节点子树规模。"""
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM idea_nodes WHERE project_id=? ORDER BY created_at, id",
            (pid,)).fetchall()]
    ideas = [_view(r) for r in rows]
    return {"ideas": ideas}


class PatchIn(BaseModel):
    title: str | None = None
    note: str | None = None
    status: str | None = None


@router.post("", status_code=201)
def create_idea(body: IdeaIn) -> dict:
    if not body.title.strip():
        raise HTTPException(422, "构思标题不能为空")
    depth = 1
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (body.pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        if body.parent_idea_id:
            parent = _get_idea(conn, body.parent_idea_id)
            if parent["project_id"] != body.pid:
                raise HTTPException(422, "父构思不属于这本书")
            if parent["status"] == "dropped":
                raise HTTPException(422, f"父构思「{parent['title']}」已放弃(冻结),"
                                         f"先回待议才能加子构思")
            depth = parent["depth"] + 1
            if depth > MAX_DEPTH:
                raise HTTPException(422, f"已达最大深度 {MAX_DEPTH}(根=1),"
                                         f"「{parent['title']}」下不能再下钻")
        iid = f"idea_{uuid.uuid4().hex[:20]}"
        now = _now()
        conn.execute(
            "INSERT INTO idea_nodes(id, project_id, parent_idea_id, title, note, status,"
            " depth, source_ref, created_at, updated_at) VALUES(?,?,?,?,?,'open',?,?,?,?)",
            (iid, body.pid, body.parent_idea_id, body.title.strip(), body.note.strip(),
             depth,
             json.dumps(body.source_ref, ensure_ascii=False) if body.source_ref else None,
             now, now))
        row = _get_idea(conn, iid)
    return {"idea": _view(row)}


@router.patch("/{iid}")
def patch_idea(iid: str, body: PatchIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    if patch.get("status") is not None and patch["status"] not in IDEA_STATUSES:
        raise HTTPException(422, f"非法状态:{patch['status']}(可选 {'/'.join(IDEA_STATUSES)})")
    if patch.get("title") is not None and not str(patch["title"]).strip():
        raise HTTPException(422, "构思标题不能为空")
    with tx() as conn:
        _get_idea(conn, iid)
        sets = ", ".join(f"{k}=?" for k in patch)
        conn.execute(f"UPDATE idea_nodes SET {sets}, updated_at=? WHERE id=?",
                     (*patch.values(), _now(), iid))
        row = _get_idea(conn, iid)
    return {"idea": _view(row)}


@router.delete("/{iid}")
def delete_idea(iid: str) -> dict:
    """删构思=删整棵子树(放弃冻结是日常收敛,删除是清理;二次确认在前端)。"""
    with tx() as conn:
        idea = _get_idea(conn, iid)
        ids = [idea["id"]]
        frontier = [idea["id"]]
        while frontier:
            marks = ",".join("?" * len(frontier))
            kids = [r["id"] for r in conn.execute(
                f"SELECT id FROM idea_nodes WHERE parent_idea_id IN ({marks})", frontier).fetchall()]
            ids.extend(kids)
            frontier = kids
        marks = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM idea_nodes WHERE id IN ({marks})", ids)
    return {"ok": True, "deleted": len(ids)}


def chain_for_context(iid: str) -> list[dict]:
    """供 conversations._context_idea 用:父链(根→自身)+冻结判定。"""
    with tx() as conn:
        idea = _get_idea(conn, iid)
        return _chain(conn, idea)


def latest_parent_digest(idea_id: str) -> str:
    """该构思最近一条非空前情提要(层叠摘要的"该层 digest";纯算法读库)。
    排序键=建线时间倒取(表无 updated_at 列;digest 随线更新,取最新线足够)。"""
    with tx() as conn:
        row = conn.execute(
            "SELECT digest FROM conversation_sessions WHERE owner_type='idea'"
            " AND owner_id=? AND digest IS NOT NULL AND digest != ''"
            " ORDER BY created_at DESC LIMIT 1", (idea_id,)).fetchone()
    return (row["digest"] or "") if row else ""
