"""L3 大纲树 API(M2,精修期第二批 C1/C2 扩展)。

层级(2026-08-31 拍板):总纲(category,UI 显示名"总纲")→ 卷 → 近纲(**可选层**:
章可直接挂卷,也可挂近纲;新建书默认不建近纲)→ 章 → 场景(beat,挂章下,五字段,
不进章节状态机)。设置页 outline.scenes_enabled 控制场景显隐(关=树与四级现状一致)。

状态机(任务书 §5):未写→草稿→人改中→待终审→定稿,另含一条打回边
待终审→人改中。跳态在代码层拒绝;只有章级走状态机。
状态时间戳 = 北极星 KPI(每章人工分钟数)的测量载体,每次变更落 l3_status_log。
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx

router = APIRouter(prefix="/api", tags=["outline"])

KIND_ORDER = {"category": 0, "volume": 1, "arc": 2, "chapter": 3, "scene": 4}
# 每种节点允许的父类型集合(近纲可选:chapter ∈ {volume, arc};scene 挂 chapter)
PARENT_KINDS = {
    "volume": {"category"},
    "arc": {"volume"},
    "chapter": {"volume", "arc"},
    "scene": {"chapter"},
}
# 场景五字段(C1 拍板,固定;键名英文入库,前端出中文 label)
SCENE_FIELDS = ("goal", "conflict", "hook", "characters", "target_words")
OUTLINE_FIELDS = ("title", "summary", "note")

TRANSITIONS = {
    "unwritten": {"draft"},
    "draft": {"human_editing"},
    "human_editing": {"final_review"},
    "final_review": {"finalized", "human_editing"},  # 打回:待终审 → 人改中
    "finalized": set(),
}

STATUS_LABELS = {
    "unwritten": "未写", "draft": "草稿", "human_editing": "人改中",
    "final_review": "待终审", "finalized": "定稿",
}


@router.get("/books/{pid}/outline")
def list_nodes(pid: str) -> dict:
    with tx() as conn:
        rows = conn.execute(
            "SELECT * FROM outline_nodes WHERE project_id=?"
            " ORDER BY parent_id IS NOT NULL, sort_order, created_at", (pid,)).fetchall()
    nodes = []
    for r in rows:
        d = dict(r)
        d["status_label"] = STATUS_LABELS.get(d["status"]) if d["kind"] == "chapter" else None
        d["allowed_transitions"] = sorted(
            TRANSITIONS.get(d["status"], set()) & set(STATUS_LABELS)
        ) if d["kind"] == "chapter" else []
        nodes.append(d)
    return {"nodes": nodes, "status_labels": STATUS_LABELS}


class NodeIn(BaseModel):
    kind: str
    parent_id: str | None = None
    title: str


@router.post("/books/{pid}/outline", status_code=201)
def create_node(pid: str, body: NodeIn) -> dict:
    if body.kind not in KIND_ORDER:
        raise HTTPException(422, f"未知节点类型: {body.kind}")
    if not body.title.strip():
        raise HTTPException(422, "标题不能为空")
    parent_kind = None
    if body.kind == "category":
        if body.parent_id:
            raise HTTPException(422, "总纲是根节点,不能有父级")
    else:
        if not body.parent_id:
            raise HTTPException(422, f"{body.kind} 必须挂在 {'/'.join(sorted(PARENT_KINDS[body.kind]))} 下")
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        if body.parent_id:
            parent = conn.execute(
                "SELECT kind FROM outline_nodes WHERE id=? AND project_id=?",
                (body.parent_id, pid)).fetchone()
            if parent is None:
                raise HTTPException(404, "父节点不存在")
            if parent["kind"] not in PARENT_KINDS[body.kind]:
                raise HTTPException(
                    422, f"{body.kind} 只能挂在 {'/'.join(sorted(PARENT_KINDS[body.kind]))} 下,"
                         f"不能挂在 {parent['kind']} 下")
            parent_kind = parent["kind"]
        order = conn.execute(
            "SELECT COALESCE(MAX(sort_order)+1, 0) FROM outline_nodes WHERE project_id=?"
            " AND COALESCE(parent_id,'')=COALESCE(?,'')", (pid, body.parent_id)).fetchone()[0]
        nid = f"node_{uuid.uuid4().hex[:20]}"
        now = _now()
        conn.execute(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title, sort_order,"
            " status, status_changed_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (nid, pid, body.parent_id, body.kind, body.title.strip(), order,
             "unwritten", now if body.kind == "chapter" else None, now, now),
        )
    return {"id": nid, "sort_order": order, "parent_kind": parent_kind}


class NodePatch(BaseModel):
    # C2 节点抽屉:标题/摘要/备注人可编辑;至少给一项
    title: str | None = None
    summary: str | None = None
    note: str | None = None


@router.put("/outline/{nid}")
def update_node(nid: str, body: NodePatch) -> dict:
    sets, params = [], []
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(422, "标题不能为空")
        sets.append("title=?")
        params.append(body.title.strip())
    if body.summary is not None:
        sets.append("summary=?")
        params.append(body.summary)
    if body.note is not None:
        sets.append("note=?")
        params.append(body.note)
    if not sets:
        raise HTTPException(422, "无字段可更新(title/summary/note 至少一项)")
    sets.append("updated_at=?")
    params.append(_now())
    params.append(nid)
    with tx() as conn:
        cur = conn.execute("SELECT id FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if cur is None:
            raise HTTPException(404, "节点不存在")
        conn.execute(f"UPDATE outline_nodes SET {', '.join(sets)} WHERE id=?", params)
    return {"ok": True}


class SceneFieldsIn(BaseModel):
    # 五键齐全提交(空串允许,键不可缺),值统一字符串
    goal: str = ""
    conflict: str = ""
    hook: str = ""
    characters: str = ""
    target_words: str = ""


@router.put("/outline/{nid}/scene-fields")
def put_scene_fields(nid: str, body: SceneFieldsIn) -> dict:
    """场景五字段编辑(C1:场景目标/冲突/出口钩子/出场角色/预计字数;仅 kind=scene)。"""
    with tx() as conn:
        node = conn.execute("SELECT kind FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "节点不存在")
        if node["kind"] != "scene":
            raise HTTPException(422, "只有场景节点有五字段")
        conn.execute(
            "UPDATE outline_nodes SET scene_fields=?, updated_at=? WHERE id=?",
            (json.dumps(body.model_dump(), ensure_ascii=False), _now(), nid))
    return {"ok": True, "scene_fields": body.model_dump()}


@router.get("/outline/{nid}/detail")
def node_detail(nid: str) -> dict:
    """节点详情(C2 抽屉数据源):本节点全字段 + 子节点 + 状态机日志(章)+ 字段历史。"""
    with tx() as conn:
        node = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "节点不存在")
        children = [dict(r) for r in conn.execute(
            "SELECT id, kind, title, sort_order, status FROM outline_nodes"
            " WHERE parent_id=? ORDER BY sort_order", (nid,)).fetchall()]
        log = [dict(r) for r in conn.execute(
            "SELECT from_status, to_status, changed_at, note FROM l3_status_log"
            " WHERE node_id=? ORDER BY changed_at", (nid,)).fetchall()]
        history = [dict(r) for r in conn.execute(
            "SELECT field, before, after, source, created_at FROM outline_field_history"
            " WHERE node_id=? ORDER BY created_at DESC LIMIT 20", (nid,)).fetchall()]
    d = dict(node)
    try:
        d["scene_fields"] = json.loads(d.get("scene_fields") or "{}")
    except json.JSONDecodeError:
        d["scene_fields"] = {}
    d["children"] = children
    d["status_log"] = log
    d["field_history"] = history
    d["status_label"] = STATUS_LABELS.get(d["status"]) if d["kind"] == "chapter" else None
    d["allowed_transitions"] = sorted(
        TRANSITIONS.get(d["status"], set()) & set(STATUS_LABELS)
    ) if d["kind"] == "chapter" else []
    return {"node": d}


class MoveIn(BaseModel):
    direction: str  # up | down


@router.post("/outline/{nid}/move")
def move_node(nid: str, body: MoveIn) -> dict:
    if body.direction not in ("up", "down"):
        raise HTTPException(422, "direction 只能是 up/down")
    with tx() as conn:
        node = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "节点不存在")
        siblings = conn.execute(
            "SELECT id, sort_order FROM outline_nodes WHERE project_id=?"
            " AND COALESCE(parent_id,'')=COALESCE(?,'') ORDER BY sort_order",
            (node["project_id"], node["parent_id"])).fetchall()
        idx = next((i for i, s in enumerate(siblings) if s["id"] == nid), None)
        if idx is None:
            raise HTTPException(500, "排序数据异常")
        j = idx - 1 if body.direction == "up" else idx + 1
        if j < 0 or j >= len(siblings):
            return {"ok": True, "note": "已到边界"}
        a, b = siblings[idx], siblings[j]
        conn.execute("UPDATE outline_nodes SET sort_order=?, updated_at=? WHERE id=?",
                     (b["sort_order"], _now(), a["id"]))
        conn.execute("UPDATE outline_nodes SET sort_order=?, updated_at=? WHERE id=?",
                     (a["sort_order"], _now(), b["id"]))
    return {"ok": True}


@router.delete("/outline/{nid}")
def delete_node(nid: str) -> dict:
    """级联删除子树(章节点若有正文,正文随节点一起删——L4 表以 node_id 为主键);
    生成任务/变更集及补丁/会话及消息一并清(S8,不留孤儿行)。"""
    with tx() as conn:
        node = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "节点不存在")
        doomed = [nid]
        frontier = [nid]
        while frontier:
            marks = ",".join("?" for _ in frontier)
            children = [r["id"] for r in conn.execute(
                f"SELECT id FROM outline_nodes WHERE parent_id IN ({marks})", frontier).fetchall()]
            doomed.extend(children)
            frontier = children
        marks = ",".join("?" for _ in doomed)
        conn.execute(f"DELETE FROM l4_texts WHERE node_id IN ({marks})", doomed)
        conn.execute(f"DELETE FROM l3_status_log WHERE node_id IN ({marks})", doomed)
        conn.execute(f"DELETE FROM outline_field_history WHERE node_id IN ({marks})", doomed)
        conn.execute(f"DELETE FROM event_chapters WHERE node_id IN ({marks})", doomed)
        # S8(审计 2026-09-01):生成任务/变更集及补丁随子树一并清
        conn.execute(f"DELETE FROM gen_tasks WHERE node_id IN ({marks})", doomed)
        conn.execute(
            f"DELETE FROM changeset_patches WHERE changeset_id IN"
            f" (SELECT id FROM changesets WHERE node_id IN ({marks}))", doomed)
        conn.execute(f"DELETE FROM changesets WHERE node_id IN ({marks})", doomed)
        # 挂在节点上的会话(审稿主讨论/节点对话/分支)随节点一并清掉;
        # 会话先删,消息必须按 session_id 前置查出再删
        sessions = [r["id"] for r in conn.execute(
            f"SELECT id FROM conversation_sessions WHERE owner_id IN ({marks})"
            " AND owner_type IN ('review','outline_node','branch')", doomed).fetchall()]
        if sessions:
            smarks = ",".join("?" for _ in sessions)
            conn.execute(f"DELETE FROM review_messages WHERE session_id IN ({smarks})", sessions)
        conn.execute(
            f"DELETE FROM conversation_sessions WHERE owner_id IN ({marks})"
            " AND owner_type IN ('review','outline_node','branch')", doomed)
        conn.execute(f"DELETE FROM outline_nodes WHERE id IN ({marks})", doomed)
    return {"ok": True, "deleted": len(doomed)}


class StatusIn(BaseModel):
    to_status: str


@router.post("/outline/{nid}/status")
def change_status(nid: str, body: StatusIn) -> dict:
    if body.to_status not in STATUS_LABELS:
        raise HTTPException(422, f"未知状态: {body.to_status}")
    with tx() as conn:
        node = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "节点不存在")
        if node["kind"] != "chapter":
            raise HTTPException(422, "只有章节点有状态机")
        allowed = TRANSITIONS.get(node["status"], set())
        if body.to_status not in allowed:
            raise HTTPException(
                409, f"非法状态迁移: {STATUS_LABELS[node['status']]} → {STATUS_LABELS[body.to_status]};"
                     f" 允许: {sorted(STATUS_LABELS[s] for s in allowed)}")
        now = _now()
        conn.execute(
            "UPDATE outline_nodes SET status=?, status_changed_at=?, updated_at=? WHERE id=?",
            (body.to_status, now, now, nid),
        )
        conn.execute(
            "INSERT INTO l3_status_log(id, node_id, from_status, to_status, changed_at)"
            " VALUES(?,?,?,?,?)",
            (f"stat_{uuid.uuid4().hex[:20]}", nid, node["status"], body.to_status, now),
        )
    return {"ok": True, "status": body.to_status, "status_changed_at": now}


@router.get("/outline/{nid}/status-log")
def status_log(nid: str) -> dict:
    with tx() as conn:
        rows = conn.execute(
            "SELECT from_status, to_status, changed_at FROM l3_status_log"
            " WHERE node_id=? ORDER BY changed_at", (nid,)).fetchall()
    return {"log": [dict(r) for r in rows]}
