"""模板双层 API(批次七⑥):用户模板存→选→套 + 预设题材包一键铺板。

- 用户模板:「存为模板」把自由板/清单卡整板序列化为 JSON 入库(本路由);
  新建图谱板时可选套用,节点/清单卡/连线完整还原(判据);
- 预设题材包:代码常量(app/graph_presets.py),payload 协议与用户模板同形,
  套用走同一条还原管道——预设与用户模板零分叉,列表分组展示(判据);
- ref 化节点(指向 l1/时间线的实体卡)跨书不可移植:存模板时降级为同名
  自由文本卡(ref 丢弃,标签/样式保留)——模板是骨架,不搬运书内实体;
- AI 起草模板内容无直写通道:AI 改图谱一律走对话建议协议(graph_add 批准
  闸门,见 graphs.py 模块注释)——判据由架构保证,本文件只提供人操作端点。
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx
from ..graph_presets import PRESET_PACKS

router = APIRouter(prefix="/api/templates", tags=["templates"])

BOARD_KINDS = ("character", "event", "item", "map", "faction", "hook",
               "power", "free", "worldview", "system")


def _payload_view(payload: str) -> dict:
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _serialize_board(conn, bid: str) -> dict:
    """板 → 模板 payload:自由节点全量留痕(含清单卡 items);ref 节点降级文本卡。"""
    board = conn.execute("SELECT * FROM graph_boards WHERE id=?", (bid,)).fetchone()
    if board is None:
        raise HTTPException(404, "图谱板不存在")
    nodes = [dict(r) for r in conn.execute(
        "SELECT * FROM graph_nodes WHERE board_id=? ORDER BY created_at", (bid,)).fetchall()]
    edges = [dict(r) for r in conn.execute(
        "SELECT * FROM graph_edges WHERE board_id=? ORDER BY created_at", (bid,)).fetchall()]
    index = {n["id"]: i for i, n in enumerate(nodes)}
    out_nodes = []
    for n in nodes:
        try:
            style = json.loads(n.get("style") or "{}")
        except json.JSONDecodeError:
            style = {}
        out_nodes.append({
            "label": n["label"], "sub_label": n["sub_label"] or "",
            "x": n["x"], "y": n["y"], "style": style,
        })
    out_edges = []
    for e in edges:
        if e["from_node_id"] in index and e["to_node_id"] in index:
            out_edges.append({"from": index[e["from_node_id"]], "to": index[e["to_node_id"]],
                              "label": e["label"] or "", "kind": e["kind"] or "其他"})
    return {"kind": board["kind"], "nodes": out_nodes, "edges": out_edges}


def _apply_payload(conn, pid: str, name: str, kind: str, payload: dict) -> dict:
    """payload → 新板+节点+边(套用还原管道,预设与用户模板共用)。"""
    now = _now()
    bid = f"gb_{uuid.uuid4().hex[:20]}"
    conn.execute(
        "INSERT INTO graph_boards(id, project_id, kind, name, grid_on, created_at,"
        " updated_at) VALUES(?,?,?,?,1,?,?)", (bid, pid, kind, name, now, now))
    id_map: dict[int, str] = {}
    for i, n in enumerate(payload.get("nodes") or []):
        nid = f"gn_{uuid.uuid4().hex[:20]}"
        id_map[i] = nid
        conn.execute(
            "INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label, sub_label,"
            " x, y, style, created_at, updated_at)"
            " VALUES(?,?,'free',NULL,?,?,?,?,?,?,?)",
            (nid, bid, str(n.get("label") or "未命名")[:60], str(n.get("sub_label") or ""),
             int(n.get("x") or 0), int(n.get("y") or 0),
             json.dumps(n.get("style") or {}, ensure_ascii=False), now, now))
    for e in payload.get("edges") or []:
        a, b = id_map.get(e.get("from")), id_map.get(e.get("to"))
        if a and b and a != b:
            conn.execute(
                "INSERT INTO graph_edges(id, board_id, from_node_id, to_node_id, label,"
                " kind, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"ge_{uuid.uuid4().hex[:20]}", bid, a, b,
                 str(e.get("label") or ""), str(e.get("kind") or "其他"), now, now))
    return {"id": bid, "name": name, "kind": kind}


class SaveIn(BaseModel):
    name: str
    board_id: str
    note: str = ""


@router.get("")
def list_templates() -> dict:
    """分组列表(判据:预设与用户模板分组显示)。"""
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, kind, payload, created_at FROM templates"
            " ORDER BY created_at DESC")]
    user = [{"id": r["id"], "name": r["name"], "kind": r["kind"],
             "node_count": len(_payload_view(r["payload"]).get("nodes") or []),
             "created_at": r["created_at"]} for r in rows]
    presets = [{"key": k, "name": p["name"], "description": p["description"],
                "board_count": len(p["boards"]),
                "boards": [{"name": b["name"], "kind": b["kind"],
                            "node_count": len(b["nodes"])} for b in p["boards"]]}
               for k, p in PRESET_PACKS.items()]
    return {"presets": presets, "user": user}


@router.post("")
def save_template(body: SaveIn) -> dict:
    if not body.name.strip():
        raise HTTPException(422, "模板名不能为空")
    with tx() as conn:
        payload = _serialize_board(conn, body.board_id)
        if not payload["nodes"]:
            raise HTTPException(422, "空板不能存为模板(至少需要一个节点)")
        tid = f"tpl_{uuid.uuid4().hex[:20]}"
        now = _now()
        conn.execute(
            "INSERT INTO templates(id, name, kind, note, payload, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (tid, body.name.strip(), payload["kind"], body.note.strip(),
             json.dumps(payload, ensure_ascii=False), now, now))
    return {"ok": True, "id": tid, "node_count": len(payload["nodes"]),
            "edge_count": len(payload["edges"])}


@router.delete("/{tid}")
def delete_template(tid: str) -> dict:
    with tx() as conn:
        if conn.execute("SELECT 1 FROM templates WHERE id=?", (tid,)).fetchone() is None:
            raise HTTPException(404, "模板不存在")
        conn.execute("DELETE FROM templates WHERE id=?", (tid,))
    return {"ok": True}


class ApplyIn(BaseModel):
    pid: str
    name: str = ""     # 缺省=模板名


@router.post("/{tid}/apply")
def apply_template(tid: str, body: ApplyIn) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
        if row is None:
            raise HTTPException(404, "模板不存在")
        if row["kind"] not in BOARD_KINDS:
            raise HTTPException(422, f"模板板型非法:{row['kind']}")
        board = _apply_payload(conn, body.pid, body.name.strip() or row["name"],
                               row["kind"], _payload_view(row["payload"]))
    return {"ok": True, "board": board}


@router.post("/packs/{key}/apply")
def apply_pack(key: str, body: ApplyIn) -> dict:
    pack = PRESET_PACKS.get(key)
    if pack is None:
        raise HTTPException(404, f"题材包不存在:{key}(可选 {'/'.join(PRESET_PACKS)})")
    created = []
    with tx() as conn:
        for b in pack["boards"]:
            created.append(_apply_payload(conn, body.pid, b["name"], b["kind"],
                                          {"nodes": b["nodes"], "edges": b.get("edges") or []}))
    return {"ok": True, "boards": created}


@router.post("/packs/{key}/boards/{idx}/apply")
def apply_pack_board(key: str, idx: int, body: ApplyIn) -> dict:
    """题材包内单板套用(新建图谱板时按板选套;整包一键走 /packs/{key}/apply)。"""
    pack = PRESET_PACKS.get(key)
    if pack is None:
        raise HTTPException(404, f"题材包不存在:{key}(可选 {'/'.join(PRESET_PACKS)})")
    if not 0 <= idx < len(pack["boards"]):
        raise HTTPException(404, f"板序号越界:{idx}(共 {len(pack['boards'])} 板)")
    b = pack["boards"][idx]
    with tx() as conn:
        board = _apply_payload(conn, body.pid, body.name.strip() or b["name"], b["kind"],
                               {"nodes": b["nodes"], "edges": b.get("edges") or []})
    return {"ok": True, "board": board}
