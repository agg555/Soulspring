"""统一图谱引擎 API(第四批,任务词 2026-09-01)。

- 图谱板(graph_boards,kind 区分)统一渲染:人物关系/剧情事件/道具/地点/势力/伏笔/
  力量/自由板/世界观;节点可 ref 既有对象(l1_entry/timeline_event)或自由建;
- 人的操作(拖动落格/手动连线/从档案生成)直接生效;AI 改动一律走 conversations
  建议协议(graph_field 轻档 / graph_add 批准闸门),本文件只提供落库端点;
- 级联:删板清节点+边;删节点清相连边;删 l1 条目同步清 ref 指向它的节点(l1 端点)。
"""
from __future__ import annotations

import json
import math
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import RELATION_KINDS, _now
from ..db import tx

router = APIRouter(prefix="/api/graphs", tags=["graphs"])

BOARD_KINDS = ("character", "event", "item", "map", "faction", "hook", "power", "free", "worldview")
EDGE_KINDS = (*RELATION_KINDS, "因果", "并行", "承接", "持有",
              "来源", "去向", "相邻", "通道", "从属", "同盟", "衍生", "克制", "自由")
NODE_FIELDS = ("label", "sub_label")
EDGE_FIELDS = ("label", "kind")


def _get_board(conn, bid: str) -> dict:
    row = conn.execute("SELECT * FROM graph_boards WHERE id=?", (bid,)).fetchone()
    if row is None:
        raise HTTPException(404, "图谱板不存在")
    return dict(row)


@router.get("/boards/{bid}")
def board_detail(bid: str) -> dict:
    with tx() as conn:
        board = _get_board(conn, bid)
        nodes = [dict(r) for r in conn.execute(
            "SELECT * FROM graph_nodes WHERE board_id=? ORDER BY created_at", (bid,)).fetchall()]
        edges = [dict(r) for r in conn.execute(
            "SELECT * FROM graph_edges WHERE board_id=? ORDER BY created_at", (bid,)).fetchall()]
        # 节点实体类型(体感三桶 2026-09-04 拍板 3a):l1 来源带 L1 类别,事件/自由单列
        ref_ids = [n["ref_id"] for n in nodes if n["ref_type"] == "l1_entry" and n["ref_id"]]
        cats: dict[str, str] = {}
        if ref_ids:
            marks = ",".join("?" * len(ref_ids))
            cats = {r["id"]: r["category"] for r in conn.execute(
                f"SELECT id, category FROM l1_entries WHERE id IN ({marks})", ref_ids).fetchall()}
    for n in nodes:
        n["style"] = json.loads(n.get("style") or "{}")
        n["category"] = cats.get(n["ref_id"] or "") if n["ref_type"] == "l1_entry" else (
            "timeline_event" if n["ref_type"] == "timeline_event" else "free")
    return {"board": board, "nodes": nodes, "edges": edges}


class BoardIn(BaseModel):
    kind: str
    name: str


@router.post("/boards/{pid}", status_code=201)
def create_board(pid: str, body: BoardIn) -> dict:
    if body.kind not in BOARD_KINDS:
        raise HTTPException(422, f"未知图谱类型: {body.kind}(可选 {'/'.join(BOARD_KINDS)})")
    if not body.name.strip():
        raise HTTPException(422, "板名不能为空")
    bid = f"gb_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        now = _now()
        conn.execute(
            "INSERT INTO graph_boards(id, project_id, kind, name, grid_on, created_at,"
            " updated_at) VALUES(?,?,?,?,1,?,?)", (bid, pid, body.kind, body.name.strip(), now, now))
        board = dict(conn.execute("SELECT * FROM graph_boards WHERE id=?", (bid,)).fetchone())
    return {"board": board}


@router.delete("/boards/{bid}")
def delete_board(bid: str) -> dict:
    with tx() as conn:
        _get_board(conn, bid)
        conn.execute("DELETE FROM graph_edges WHERE board_id=?", (bid,))
        conn.execute("DELETE FROM graph_nodes WHERE board_id=?", (bid,))
        conn.execute("DELETE FROM graph_boards WHERE id=?", (bid,))
    return {"ok": True}


class BoardPatch(BaseModel):
    grid_on: int | None = None
    name: str | None = None


@router.patch("/boards/{bid}")
def patch_board(bid: str, body: BoardPatch) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    if patch.get("name") is not None and not str(patch["name"]).strip():
        raise HTTPException(422, "板名不能为空")
    sets = ", ".join(f"{k}=?" for k in patch)
    with tx() as conn:
        _get_board(conn, bid)
        conn.execute(f"UPDATE graph_boards SET {sets}, updated_at=? WHERE id=?",
                     (*patch.values(), _now(), bid))
        board = dict(conn.execute("SELECT * FROM graph_boards WHERE id=?", (bid,)).fetchone())
    return {"board": board}


class NodeIn(BaseModel):
    label: str
    sub_label: str | None = None
    ref_type: str = "free"          # l1_entry|timeline_event|free
    ref_id: str | None = None
    x: float = 0
    y: float = 0


@router.post("/boards/{bid}/nodes", status_code=201)
def create_node(bid: str, body: NodeIn) -> dict:
    if not body.label.strip():
        raise HTTPException(422, "节点名不能为空")
    if body.ref_type not in ("l1_entry", "timeline_event", "free"):
        raise HTTPException(422, f"未知 ref_type: {body.ref_type}")
    nid = f"gn_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        _get_board(conn, bid)
        conn.execute(
            "INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label, sub_label,"
            " x, y, style, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (nid, bid, body.ref_type, body.ref_id, body.label.strip(), body.sub_label,
             body.x, body.y, "{}", _now(), _now()))
        node = dict(conn.execute("SELECT * FROM graph_nodes WHERE id=?", (nid,)).fetchone())
    return {"node": node}


class NodePatch(BaseModel):
    x: float | None = None
    y: float | None = None
    label: str | None = None
    sub_label: str | None = None


@router.patch("/nodes/{nid}")
def patch_node(nid: str, body: NodePatch) -> dict:
    """拖动落格持久化(x/y)与字段修改共用;至少一项。"""
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    if patch.get("label") is not None and not str(patch["label"]).strip():
        raise HTTPException(422, "节点名不能为空")
    sets = ", ".join(f"{k}=?" for k in patch)
    with tx() as conn:
        if conn.execute("SELECT 1 FROM graph_nodes WHERE id=?", (nid,)).fetchone() is None:
            raise HTTPException(404, "节点不存在")
        conn.execute(f"UPDATE graph_nodes SET {sets}, updated_at=? WHERE id=?",
                     (*patch.values(), _now(), nid))
        node = dict(conn.execute("SELECT * FROM graph_nodes WHERE id=?", (nid,)).fetchone())
    return {"node": node}


@router.delete("/nodes/{nid}")
def delete_node(nid: str) -> dict:
    with tx() as conn:
        if conn.execute("SELECT 1 FROM graph_nodes WHERE id=?", (nid,)).fetchone() is None:
            raise HTTPException(404, "节点不存在")
        conn.execute(
            "DELETE FROM graph_edges WHERE from_node_id=? OR to_node_id=?", (nid, nid))
        conn.execute("DELETE FROM graph_nodes WHERE id=?", (nid,))
    return {"ok": True}


class EdgeIn(BaseModel):
    from_node_id: str
    to_node_id: str
    label: str = ""
    kind: str = "其他"


@router.post("/boards/{bid}/edges", status_code=201)
def create_edge(bid: str, body: EdgeIn) -> dict:
    """A4 自动连线与手动建边共用;同一对节点允许多条线(A6)。"""
    if body.kind not in EDGE_KINDS:
        raise HTTPException(422, f"未知关系类别: {body.kind}")
    if body.from_node_id == body.to_node_id:
        raise HTTPException(422, "不能连接节点自身")
    eid = f"ge_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        _get_board(conn, bid)
        for n in (body.from_node_id, body.to_node_id):
            if conn.execute("SELECT 1 FROM graph_nodes WHERE id=?", (n,)).fetchone() is None:
                raise HTTPException(404, "端点节点不存在")
        conn.execute(
            "INSERT INTO graph_edges(id, board_id, from_node_id, to_node_id, label, kind,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (eid, bid, body.from_node_id, body.to_node_id, body.label.strip(),
             body.kind, _now(), _now()))
        edge = dict(conn.execute("SELECT * FROM graph_edges WHERE id=?", (eid,)).fetchone())
    return {"edge": edge}


class EdgePatch(BaseModel):
    label: str | None = None
    kind: str | None = None


@router.patch("/edges/{eid}")
def patch_edge(eid: str, body: EdgePatch) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    if patch.get("kind") not in (None, *EDGE_KINDS):
        raise HTTPException(422, f"未知关系类别: {patch['kind']}")
    sets = ", ".join(f"{k}=?" for k in patch)
    with tx() as conn:
        if conn.execute("SELECT 1 FROM graph_edges WHERE id=?", (eid,)).fetchone() is None:
            raise HTTPException(404, "连线不存在")
        conn.execute(f"UPDATE graph_edges SET {sets}, updated_at=? WHERE id=?",
                     (*patch.values(), _now(), eid))
        edge = dict(conn.execute("SELECT * FROM graph_edges WHERE id=?", (eid,)).fetchone())
    return {"edge": edge}


@router.delete("/edges/{eid}")
def delete_edge(eid: str) -> dict:
    with tx() as conn:
        if conn.execute("SELECT 1 FROM graph_edges WHERE id=?", (eid,)).fetchone() is None:
            raise HTTPException(404, "连线不存在")
        conn.execute("DELETE FROM graph_edges WHERE id=?", (eid,))
    return {"ok": True}


class GenerateIn(BaseModel):
    source: str                     # l1_entry | timeline_event
    category: str | None = None     # source=l1_entry 时的条目类别
    board_kind: str | None = None   # 源板缺省时自动建板的 kind


@router.post("/boards/{bid}/generate", status_code=201)
def generate_nodes(bid: str, body: GenerateIn) -> dict:
    """B:一键生成节点(人的操作直接生效;AI 批量生成走提案闸门)。

    从 l1 confirmed 条目 / 时间线事件生成方框节点,已存在同 ref 的跳过;
    新节点网格排布(从画布右上空位起,4 列折行)。
    """
    created, skipped = [], 0
    with tx() as conn:
        board = _get_board(conn, bid)
        existing = {r["ref_id"] for r in conn.execute(
            "SELECT ref_id FROM graph_nodes WHERE board_id=? AND ref_id IS NOT NULL",
            (bid,)).fetchall()}
        if body.source == "l1_entry":
            if not body.category:
                raise HTTPException(422, "l1_entry 来源需要 category")
            rows = conn.execute(
                "SELECT id, name FROM l1_entries WHERE project_id=? AND category=?"
                " AND entry_status='confirmed' ORDER BY name",
                (board["project_id"], body.category)).fetchall()
            pairs = [(r["id"], r["name"], None) for r in rows]
        elif body.source == "timeline_event":
            rows = conn.execute(
                "SELECT id, title, time_label FROM timeline_events"
                " WHERE project_id=? ORDER BY sort_key", (board["project_id"],)).fetchall()
            pairs = [(r["id"], r["title"], r["time_label"]) for r in rows]
        else:
            raise HTTPException(422, f"未知生成来源: {body.source}")

        count = len(existing)
        for ref_id, label, sub in pairs:
            if ref_id in existing:
                skipped += 1
                continue
            col, rowi = count % 4, count // 4
            nid = f"gn_{uuid.uuid4().hex[:20]}"
            now = _now()
            conn.execute(
                "INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label, sub_label,"
                " x, y, style, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (nid, bid, body.source, ref_id, label, sub,
                 80 + col * 190, 60 + rowi * 110, "{}", now, now))
            created.append(nid)
            count += 1
    return {"ok": True, "created": len(created), "skipped": skipped}


# ── 图谱中心:板列表 ──

@router.get("/books/{pid}/boards")
def list_boards(pid: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT b.*, (SELECT COUNT(*) FROM graph_nodes n WHERE n.board_id=b.id) AS node_count,"
            " (SELECT COUNT(*) FROM graph_edges e WHERE e.board_id=b.id) AS edge_count"
            " FROM graph_boards b WHERE b.project_id=? ORDER BY b.created_at", (pid,)).fetchall()]
    return {"boards": rows, "kinds": list(BOARD_KINDS)}
