"""建议采纳 API(S1 三拆自 conversations.py,纯移动零行为变化)。

两档采纳规则(执行书拍板):
- 轻档(outline_field/event_field/graph_field):人已在抽屉确认 diff,直接写回并留痕
  outline_field_history;
- 重档(chapter_text):修改段落作为 patch 追加进该章变更集(与 AI 自修同管道);
- graph_add:批准闸门,建节点/连线落统一图谱引擎。
"""
from __future__ import annotations

import json
import math
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import EVENT_FIELDS, EDGE_KINDS, _now
from ..db import tx
from .changeset_ops import (
    _carry_dismissals,
    _changeset_view,
    _code_audit,
    _get_node,
    _open_changeset,
    _put_patch,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

OUTLINE_FIELDS = ("title", "summary", "note")
GRAPH_NODE_FIELDS = ("label", "sub_label")
GRAPH_EDGE_FIELDS = ("label", "kind")


class AdoptIn(BaseModel):
    session_id: str
    message_id: str
    index: int
    anchor: dict | None = None  # 速赢 2.1:图谱新增落位锚 {x,y}(前端画布坐标),可空


@router.post("/suggestions/adopt")
def adopt_suggestion(body: AdoptIn) -> dict:
    with tx() as conn:
        msg = conn.execute(
            "SELECT * FROM review_messages WHERE id=? AND session_id=?",
            (body.message_id, body.session_id)).fetchone()
    if msg is None or msg["role"] != "assistant":
        raise HTTPException(404, "建议所在消息不存在")
    try:
        meta = json.loads(msg["meta"]) if msg["meta"] else {}
    except json.JSONDecodeError:
        meta = {}
    suggestions = meta.get("suggestions") or []
    if body.index < 0 or body.index >= len(suggestions):
        raise HTTPException(422, "建议序号无效")
    sug = suggestions[body.index]
    if sug.get("adopted"):
        raise HTTPException(409, "该建议已采纳过")

    target_type = sug.get("target_type")
    target = sug.get("target") or {}
    if target_type == "outline_field":
        result = _adopt_outline_field(sug, target)
    elif target_type == "chapter_text":
        result = _adopt_chapter_text(sug, target)
    elif target_type == "event_field":
        result = _adopt_event_field(sug, target)
    elif target_type == "graph_field":
        result = _adopt_graph_field(sug, target)
    elif target_type == "graph_add":
        result = _adopt_graph_add(sug, target, anchor=body.anchor)
    else:
        raise HTTPException(422, "该建议没有可落地的目标(大纲字段/正文/事件/图谱对象可采纳)")

    sug["adopted"] = True
    sug["adopted_at"] = _now()
    sug["adopt_summary"] = result.get("summary", "")
    meta["suggestions"] = suggestions
    with tx() as conn:
        conn.execute("UPDATE review_messages SET meta=? WHERE id=?",
                     (json.dumps(meta, ensure_ascii=False), body.message_id))
    return {"ok": True, **result}


def _adopt_outline_field(sug: dict, target: dict) -> dict:
    """轻档:人已在抽屉确认 diff,这里写回节点字段并留 AgentRun 痕。"""
    nid = target.get("node_id")
    field = target.get("field")
    value = str(target.get("value") or "").strip()
    if field not in OUTLINE_FIELDS:
        raise HTTPException(422, f"字段 {field} 不支持轻档写回(仅 title/summary/note)")
    if not value:
        raise HTTPException(422, "建议缺少新字段值")
    with tx() as conn:
        node = conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "目标节点不存在")
        before = node[field] or ""
        now = _now()
        conn.execute(f"UPDATE outline_nodes SET {field}=?, updated_at=? WHERE id=?",
                     (value, now, nid))
        conn.execute(
            "INSERT INTO agent_runs(id, project_id, node_id, action, agent_type, status,"
            " input_summary, finished_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (f"run_{uuid.uuid4().hex[:20]}", node["project_id"], nid,
             "adopt_outline_suggestion", "human_gate", "succeeded",
             f"节点「{node['title']}」.{field}:「{(before or '(空)')[:60]}」"
             f"→「{value[:60]}」(对话建议采纳)", now, now))
    return {"target": "outline_field", "node_id": nid, "field": field,
            "before": before, "after": value, "summary": f"已写回节点字段 {field}"}


def _adopt_chapter_text(sug: dict, target: dict) -> dict:
    """重档:起草修改段落作为 patch 追加进该章变更集(与 AI 自修同管道,人改工作区再合入)。"""
    nid = target.get("node_id")
    revised = str(target.get("revised_text") or "").strip()
    if not revised:
        raise HTTPException(422, "建议缺少修改后文本(revised_text)")
    with tx() as conn:
        row = conn.execute("SELECT project_id FROM outline_nodes WHERE id=?", (nid,)).fetchone()
    if row is None:
        raise HTTPException(404, "目标章节点不存在")
    node = _get_node(row["project_id"], nid)
    cs = _open_changeset(nid)
    if cs is None:
        raise HTTPException(409, "该章没有打开的变更集,请先在工作台生成草稿,正文类建议才能进入变更集")
    view = _changeset_view(cs)
    validations, _ = _code_audit(node["project_id"], node, revised)
    _carry_dismissals(validations, view["validations"])
    with tx() as conn:
        conn.execute(
            "UPDATE changesets SET status='draft', validations=?, updated_at=? WHERE id=?",
            (json.dumps(validations, ensure_ascii=False), _now(), cs["id"]))
        _put_patch(conn, cs["id"], nid, revised, "对话建议采纳",
                   cs.get("base_revision"), source="ai")
        fresh = dict(conn.execute("SELECT * FROM changesets WHERE id=?", (cs["id"],)).fetchone())
    return {"target": "chapter_text", "changeset": _changeset_view(fresh),
            "summary": "修改已作为新版本进入该章变更集(工作台人改区可查看)"}


def _adopt_event_field(sug: dict, target: dict) -> dict:
    """事件字段轻档采纳(第三批 E):写回 timeline_events,留痕 outline_field_history。"""
    eid = target.get("event_id")
    field = target.get("field")
    value = str(target.get("value") or "").strip()
    if field not in EVENT_FIELDS:
        raise HTTPException(422, f"事件字段 {field} 不支持轻档写回")
    if not value:
        raise HTTPException(422, "建议缺少新字段值")
    if field in ("line", "status") and value not in ("主线", "支线", "已定", "未定"):
        raise HTTPException(422, "line 只能是 主线/支线;status 只能是 已定/未定")
    with tx() as conn:
        evt = conn.execute("SELECT * FROM timeline_events WHERE id=?", (eid,)).fetchone()
        if evt is None:
            raise HTTPException(404, "目标事件不存在")
        before = evt[field] or ""
        now = _now()
        conn.execute(f"UPDATE timeline_events SET {field}=?, updated_at=? WHERE id=?",
                     (value, now, eid))
        conn.execute(
            "INSERT INTO outline_field_history(id, node_id, node_type, field, before,"
            " after, source, session_id, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (f"fh_{uuid.uuid4().hex[:20]}", eid, "event", field, before, value,
             "suggestion_adopt", None, now))
    return {"target": "event_field", "event_id": eid, "field": field,
            "before": before, "after": value, "summary": f"已写回事件字段 {field}"}


def _adopt_graph_field(sug: dict, target: dict) -> dict:
    """图谱字段轻档采纳(第四批 D):写回节点(label/sub_label)或连线(label/kind)。"""
    value = str(target.get("value") or "").strip()
    if not value:
        raise HTTPException(422, "建议缺少新字段值")
    now = _now()
    if target.get("node_id"):
        nid, field = target["node_id"], target.get("field")
        if field not in GRAPH_NODE_FIELDS:
            raise HTTPException(422, f"图谱节点字段 {field} 不支持轻档写回")
        with tx() as conn:
            node = conn.execute("SELECT * FROM graph_nodes WHERE id=?", (nid,)).fetchone()
            if node is None:
                raise HTTPException(404, "目标图谱节点不存在")
            before = node[field] or ""
            conn.execute(f"UPDATE graph_nodes SET {field}=?, updated_at=? WHERE id=?",
                         (value, now, nid))
            conn.execute(
                "INSERT INTO outline_field_history(id, node_id, node_type, field, before,"
                " after, source, session_id, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (f"fh_{uuid.uuid4().hex[:20]}", nid, "graph_node", field, before, value,
                 "suggestion_adopt", None, now))
        return {"target": "graph_field", "node_id": nid, "field": field,
                "before": before, "after": value, "summary": f"已写回图谱节点 {field}"}
    if target.get("edge_id"):
        eid, field = target["edge_id"], target.get("field")
        if field not in GRAPH_EDGE_FIELDS:
            raise HTTPException(422, f"图谱连线字段 {field} 不支持轻档写回")
        if field == "kind" and value not in EDGE_KINDS:
            raise HTTPException(422, f"未知关系类别: {value}")
        with tx() as conn:
            edge = conn.execute("SELECT * FROM graph_edges WHERE id=?", (eid,)).fetchone()
            if edge is None:
                raise HTTPException(404, "目标图谱连线不存在")
            before = edge[field] or ""
            conn.execute(f"UPDATE graph_edges SET {field}=?, updated_at=? WHERE id=?",
                         (value, now, eid))
            conn.execute(
                "INSERT INTO outline_field_history(id, node_id, node_type, field, before,"
                " after, source, session_id, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (f"fh_{uuid.uuid4().hex[:20]}", eid, "graph_edge", field, before, value,
                 "suggestion_adopt", None, now))
        return {"target": "graph_field", "edge_id": eid, "field": field,
                "before": before, "after": value, "summary": f"已写回图谱连线 {field}"}
    raise HTTPException(422, "graph_field 建议缺少 node_id/edge_id")


def _adopt_graph_add(sug: dict, target: dict, anchor: dict | None = None) -> dict:
    """图谱新增采纳(批准闸门:前端预览弹窗人已确认):建节点或连线。"""
    board_id = target.get("board_id")
    item = target.get("item") or {}
    with tx() as conn:
        board = conn.execute("SELECT * FROM graph_boards WHERE id=?", (board_id,)).fetchone()
        if board is None:
            raise HTTPException(404, "目标图谱板不存在")
        now = _now()
        if item.get("type") == "node":
            label = str(item.get("label") or "").strip()
            if not label:
                raise HTTPException(422, "建议新增节点缺少 label")
            # 空位排布(速赢 2.1,2026-09-03):优先以采纳锚(边中点/源节点)为心
            # 环绕找与现有节点保持间距的格;无锚或环绕失败再退回左上全局网格(旧行为)。
            used = [(n["x"], n["y"]) for n in conn.execute(
                "SELECT x, y FROM graph_nodes WHERE board_id=?", (board_id,)).fetchall()]
            spot = None
            if anchor:
                try:
                    ax, ay = float(anchor["x"]), float(anchor["y"])
                except (KeyError, TypeError, ValueError):
                    ax = None
                if ax is not None:
                    # 以锚为心,半径递增、每圈 12 方向,取第一个与所有节点间距 ≥90 的 10px 格点
                    for radius in (120, 190, 260, 330):
                        for k in range(12):
                            ang = 2 * math.pi * k / 12
                            cand = (round((ax + radius * math.cos(ang)) / 10) * 10,
                                    round((ay + radius * math.sin(ang)) / 10) * 10)
                            if all((cand[0] - ux) ** 2 + (cand[1] - uy) ** 2 >= 90 ** 2
                                   for ux, uy in used):
                                spot = cand
                                break
                        if spot:
                            break
            if spot is None:
                # 退回全局网格(旧行为):左上起第一个不重叠格
                used_set = {(round(ux), round(uy)) for ux, uy in used}
                idx = 0
                while spot is None:
                    x, y = 80 + (idx % 4) * 190, 60 + (idx // 4) * 110
                    if (x, y) not in used_set:
                        spot = (x, y)
                    idx += 1
                    if idx > 200:
                        spot = (x, y)
            nid = f"gn_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label, sub_label,"
                " x, y, style, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (nid, board_id, "free", None, label,
                 str(item.get("sub_label") or "") or None, spot[0], spot[1], "{}", now, now))
            return {"target": "graph_add", "board_id": board_id, "node_id": nid,
                    "summary": f"已在图谱板新增节点「{label}」"}
        if item.get("type") == "edge":
            def _resolve_endpoint(v) -> str | None:
                """端点兼容 id 或 label(模型常引用建议里刚新建、尚无 id 的节点名)。"""
                if not v:
                    return None
                row = conn.execute(
                    "SELECT id FROM graph_nodes WHERE id=?", (str(v),)).fetchone()
                if row:
                    return row["id"]
                row = conn.execute(
                    "SELECT id FROM graph_nodes WHERE board_id=? AND label=?",
                    (board_id, str(v))).fetchone()
                return row["id"] if row else None
            a = _resolve_endpoint(item.get("from_node_id"))
            b = _resolve_endpoint(item.get("to_node_id"))
            if not a or not b or a == b:
                raise HTTPException(422, "建议新增连线的端点无法解析(需节点 id 或同板已有节点名)")
            kind = item.get("kind") or "自由"
            eid = f"ge_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO graph_edges(id, board_id, from_node_id, to_node_id, label,"
                " kind, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (eid, board_id, a, b, str(item.get("label") or "").strip(), kind, now, now))
            return {"target": "graph_add", "board_id": board_id, "edge_id": eid,
                    "summary": "已在图谱板新增连线"}
        raise HTTPException(422, "graph_add 建议缺少 item 或 type 不明")
