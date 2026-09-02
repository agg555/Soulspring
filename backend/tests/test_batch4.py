"""第四批回归(统一图谱引擎/迁移/级联/graph 采纳,任务词 2026-09-01)。"""
import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    yield dbmod
    dbmod._conn = None


def _seed_book_with_relation():
    """建书 + 两个角色 + 一条 character_relations(v10 旧表)→ 触发 v11 迁移场景。"""
    from app.db import tx
    with tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at)"
            " VALUES('p1','测试书','2026-09-01','2026-09-01')")
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, created_at,"
            " updated_at) VALUES('e1','p1','character','陈昼','主角','t','t')")
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, created_at,"
            " updated_at) VALUES('e2','p1','character','陈夜','兄长','t','t')")
        conn.execute(
            "INSERT INTO character_relations(id, project_id, from_entry_id, to_entry_id,"
            " relation, kind, created_at) VALUES('r1','p1','e1','e2','七年前的兄长','亲情','t')")


def test_v11_migration_from_character_relations(tmp_db):
    """旧 character_relations 一次性迁入统一引擎:板/节点(ref l1_entry)/边齐全,旧表保留。"""
    from app.db import migrate_character_relations_to_graph, tx
    _seed_book_with_relation()   # fixture 已迁到 v11;手动触发迁移函数(存量场景)
    with tx() as conn:
        migrate_character_relations_to_graph(conn)
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 11
        boards = conn.execute("SELECT * FROM graph_boards WHERE kind='character'").fetchall()
        assert len(boards) == 1
        bid = boards[0]["id"]
        nodes = conn.execute(
            "SELECT ref_type, ref_id, label FROM graph_nodes WHERE board_id=?", (bid,)).fetchall()
        edges = conn.execute(
            "SELECT label, kind FROM graph_edges WHERE board_id=?", (bid,)).fetchall()
        old = conn.execute("SELECT COUNT(*) c FROM character_relations").fetchone()["c"]
    assert {n["label"] for n in nodes} == {"陈昼", "陈夜"}
    assert all(n["ref_type"] == "l1_entry" for n in nodes)
    assert edges[0]["label"] == "七年前的兄长" and edges[0]["kind"] == "亲情"
    assert old == 1   # 旧表保留只读对照


def test_board_node_edge_crud_and_position(tmp_db):
    """板/节点/边 CRUD;PATCH x/y 拖动落格持久化(判据②)。"""
    _seed_book_with_relation()
    from app.routers.graphs import (
        BoardIn, EdgeIn, EdgePatch, NodeIn, NodePatch, create_board, create_edge,
        create_node, delete_edge, delete_node, patch_edge, patch_node,
    )
    with pytest.raises(HTTPException):
        create_board("p1", BoardIn(kind="不存在", name="x"))
    b = create_board("p1", BoardIn(kind="free", name="头脑风暴"))["board"]
    n1 = create_node(b["id"], NodeIn(label="点A", x=100, y=80))["node"]
    n2 = create_node(b["id"], NodeIn(label="点B", x=300, y=80))["node"]
    # 拖动持久化(吸附后的坐标)
    moved = patch_node(n1["id"], NodePatch(x=140, y=120))["node"]
    assert (moved["x"], moved["y"]) == (140, 120)
    # 建边 + 改标签/类别 + 删;自环与未知类别拒绝
    e = create_edge(b["id"], EdgeIn(from_node_id=n1["id"], to_node_id=n2["id"],
                                    label="试一把", kind="自由"))["edge"]
    with pytest.raises(HTTPException):
        create_edge(b["id"], EdgeIn(from_node_id=n1["id"], to_node_id=n1["id"], kind="自由"))
    with pytest.raises(HTTPException):
        create_edge(b["id"], EdgeIn(from_node_id=n1["id"], to_node_id=n2["id"],
                                    kind="不是类别"))
    patched = patch_edge(e["id"], EdgePatch(label="改标签", kind="因果"))["edge"]
    assert patched["kind"] == "因果"
    # 删节点级联清边;删边独立
    delete_node(n2["id"])
    with pytest.raises(HTTPException):
        patch_edge(e["id"], EdgePatch(label="x"))
    n3 = create_node(b["id"], NodeIn(label="点C", x=500, y=80))["node"]
    e2 = create_edge(b["id"], EdgeIn(from_node_id=n1["id"], to_node_id=n3["id"], kind="自由"))["edge"]
    delete_edge(e2["id"])


def test_generate_nodes_from_l1_and_dedupe(tmp_db):
    """从 l1 confirmed 一键生成(判据⑦):重复 ref 跳过;时间线来源同理。"""
    from app.db import tx
    from app.routers.graphs import BoardIn, GenerateIn, create_board, generate_nodes
    _seed_book_with_relation()
    with tx() as conn:
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, created_at,"
            " updated_at) VALUES('i1','p1','item_economy','赤霄剑','x','t','t')")
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, created_at,"
            " updated_at) VALUES('i2','p1','item_economy','铜灯','y','t','t')")
    b = create_board("p1", BoardIn(kind="item", name="道具图谱"))["board"]
    r1 = generate_nodes(b["id"], GenerateIn(source="l1_entry", category="item_economy"))
    assert r1["created"] == 2
    r2 = generate_nodes(b["id"], GenerateIn(source="l1_entry", category="item_economy"))
    assert r2["created"] == 0 and r2["skipped"] == 2   # 同 ref 去重


def test_delete_l1_entry_cascades_graph_nodes(tmp_db):
    """删 l1 条目 → ref 指向它的图谱节点与相连边级联清(判据⑧图谱版)。"""
    from app.db import tx
    from app.routers.graphs import (
        BoardIn, EdgeIn, NodeIn, create_board, create_edge, create_node,
    )
    _seed_book_with_relation()
    b = create_board("p1", BoardIn(kind="character", name="人物关系"))["board"]
    na = create_node(b["id"], NodeIn(label="陈昼", ref_type="l1_entry", ref_id="e1"))["node"]
    nb = create_node(b["id"], NodeIn(label="自由点"))["node"]
    create_edge(b["id"], EdgeIn(from_node_id=na["id"], to_node_id=nb["id"], kind="自由"))
    from app.routers.l1 import delete_entry
    delete_entry("e1")
    with tx() as conn:
        left = conn.execute("SELECT label FROM graph_nodes WHERE board_id=?", (b["id"],)).fetchall()
        edges = conn.execute("SELECT COUNT(*) c FROM graph_edges WHERE board_id=?", (b["id"],)).fetchone()["c"]
    assert [x["label"] for x in left] == ["自由点"]
    assert edges == 0


def _seed_graph_suggestion(sid, msg_id, target_type, target):
    import json as _json
    from app.db import tx
    meta = {"suggestions": [{"quote": "", "issue": "x", "suggestion": "y",
                             "severity": "major", "target_type": target_type,
                             "target": target}]}
    with tx() as conn:
        conn.execute(
            "INSERT INTO review_messages(id, session_id, role, content, meta, created_at)"
            " VALUES(?, ?, 'assistant', 'r', ?, 't')", (msg_id, sid, _json.dumps(meta)))
    return msg_id


def test_adopt_graph_field_and_add(tmp_db):
    """graph_field 轻档(写回+graph_node/graph_edge 留痕);graph_add 批准后落库(判据⑨⑩)。"""
    from app.db import tx
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    from app.routers.graphs import (
        BoardIn, EdgeIn, NodeIn, create_board, create_edge, create_node,
    )
    _seed_book_with_relation()
    b = create_board("p1", BoardIn(kind="free", name="板"))["board"]
    n1 = create_node(b["id"], NodeIn(label="点A", x=0, y=0))["node"]
    n2 = create_node(b["id"], NodeIn(label="点B", x=190, y=0))["node"]
    e = create_edge(b["id"], EdgeIn(from_node_id=n1["id"], to_node_id=n2["id"],
                                    label="旧", kind="自由"))["edge"]
    sid = create_session(SessionIn(
        owner_type="graph_node", owner_id=n1["id"], name="s"))["session"]["id"]
    msg = _seed_graph_suggestion(sid, "m1", "graph_field",
                                 {"node_id": n1["id"], "field": "label", "value": "新名"})
    r = adopt_suggestion(AdoptIn(session_id=sid, message_id=msg, index=0))
    assert r["after"] == "新名"
    sid2 = create_session(SessionIn(
        owner_type="graph_edge", owner_id=e["id"], name="s2"))["session"]["id"]
    msg2 = _seed_graph_suggestion(sid2, "m2", "graph_field",
                                  {"edge_id": e["id"], "field": "kind", "value": "因果"})
    adopt_suggestion(AdoptIn(session_id=sid2, message_id=msg2, index=0))
    with tx() as conn:
        kinds = {r["node_type"] for r in conn.execute(
            "SELECT node_type FROM outline_field_history WHERE after='新名' OR after='因果'").fetchall()}
        edge_kind = conn.execute(
            "SELECT kind FROM graph_edges WHERE id=?", (e["id"],)).fetchone()["kind"]
    assert kinds == {"graph_node", "graph_edge"}
    assert edge_kind == "因果"
    # graph_add:节点与连线(批准闸门确认后)
    msg3 = _seed_graph_suggestion(sid, "m3", "graph_add",
                                  {"board_id": b["id"],
                                   "item": {"type": "node", "label": "派生点"}})
    r3 = adopt_suggestion(AdoptIn(session_id=sid, message_id=msg3, index=0))
    assert r3["node_id"]
    msg4 = _seed_graph_suggestion(sid, "m4", "graph_add",
                                  {"board_id": b["id"],
                                   "item": {"type": "edge", "from_node_id": n1["id"],
                                            "to_node_id": r3["node_id"],
                                            "label": "派生", "kind": "衍生"}})
    r4 = adopt_suggestion(AdoptIn(session_id=sid, message_id=msg4, index=0))
    assert r4["edge_id"]
    with pytest.raises(HTTPException):
        msg5 = _seed_graph_suggestion(sid, "m5", "graph_field",
                                      {"node_id": n1["id"], "field": "x", "value": "1"})
        adopt_suggestion(AdoptIn(session_id=sid, message_id=msg5, index=0))
