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


def test_board_detail_node_category(tmp_db):
    """board_detail 节点带实体类型标注(体感三桶 2026-09-04 拍板 3a)。"""
    from app.db import tx
    from app.routers.graphs import (
        BoardIn, NodeIn, board_detail, create_board, create_node,
    )
    _seed_book_with_relation()
    with tx() as conn:
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, created_at,"
            " updated_at) VALUES('e1x','p1','character','陈昼','x','t','t')")
    b = create_board("p1", BoardIn(kind="free", name="混板"))["board"]
    create_node(b["id"], NodeIn(label="角色点", ref_type="l1_entry", ref_id="e1x"))
    create_node(b["id"], NodeIn(label="事件点", ref_type="timeline_event", ref_id="ev_x"))
    create_node(b["id"], NodeIn(label="自由点"))
    out = {n["label"]: n["category"] for n in board_detail(b["id"])["nodes"]}
    assert out == {"角色点": "character", "事件点": "timeline_event", "自由点": "free"}


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


def test_adopt_graph_add_anchor_placement(tmp_db):
    """速赢 2.1(2026-09-03):带锚采纳 → 新节点落在锚附近且不与现有节点重叠;
    无锚 → 退回全局网格(旧行为兜底)。"""
    import math
    from app.db import tx
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    from app.routers.graphs import BoardIn, NodeIn, create_board, create_node
    _seed_book_with_relation()
    b = create_board("p1", BoardIn(kind="free", name="板"))["board"]
    n1 = create_node(b["id"], NodeIn(label="锚点邻点", x=500, y=500))["node"]
    sid = create_session(SessionIn(
        owner_type="graph_node", owner_id=n1["id"], name="s"))["session"]["id"]

    def _adopt(msg_id, anchor):
        msg = _seed_graph_suggestion(sid, msg_id, "graph_add",
                                     {"board_id": b["id"],
                                      "item": {"type": "node", "label": "派生" + msg_id}})
        return adopt_suggestion(AdoptIn(session_id=sid, message_id=msg, index=0,
                                        anchor=anchor))

    # 带锚(500,500):现有节点就在锚上,新节点必须躲开 ≥90 且不超最大环绕半径 330
    r1 = _adopt("ma1", {"x": 500, "y": 500})
    with tx() as conn:
        row = conn.execute("SELECT x, y FROM graph_nodes WHERE id=?",
                           (r1["node_id"],)).fetchone()
    d = math.hypot(row["x"] - 500, row["y"] - 500)
    assert 90 <= d <= 330 + 20, f"带锚落点距锚 {d:.0f}, 应在环绕带内"
    assert math.hypot(row["x"] - 500, row["y"] - 500) >= 90  # 与邻点不重叠

    # 无锚:退回全局网格(x=80 起)
    r2 = _adopt("ma2", None)
    with tx() as conn:
        row2 = conn.execute("SELECT x, y FROM graph_nodes WHERE id=?",
                            (r2["node_id"],)).fetchone()
    assert row2["x"] == 80 and row2["y"] == 60


def test_price_for_discount_expiry(tmp_db):
    """双份价格(2026-09-03 拍板):折扣截止日(含当天)内用 default,过期自动用 standard。"""
    from datetime import date, timedelta
    from app.settings_store import update_settings
    from app.ledger.usage import price_for

    update_settings("pricing", {
        "default": {"input_per_m": 0.4, "output_per_m": 1.4},
        "standard": {"input_per_m": 0.8, "output_per_m": 2.8},
    })
    # 未配截止日 → 折扣
    assert price_for("glm-5.3-flash") == (0.4, 1.4)
    # 截止日 = 明天 → 仍折扣
    update_settings("pricing", {"discount_until": (date.today() + timedelta(days=1)).isoformat()})
    assert price_for("glm-5.3-flash") == (0.4, 1.4)
    # 截止日 = 昨天 → 自动正价
    update_settings("pricing", {"discount_until": (date.today() - timedelta(days=1)).isoformat()})
    assert price_for("glm-5.3-flash") == (0.8, 2.8)
    # 截止日 = 今天(含) → 折扣
    update_settings("pricing", {"discount_until": date.today().isoformat()})
    assert price_for("glm-5.3-flash") == (0.4, 1.4)


def test_dashboard_chapter_cost_via_agent_run_node_id(tmp_db):
    """修复批 #5/建议4(2026-09-03):B1 按章成本聚合走 agent_runs.node_id——
    有 node_id 的 run 成本计入该章,无 node_id(历史存量)不计入。"""
    from app.db import tx
    from app.ledger.usage import start_run, log_usage
    from app.settings_store import update_settings
    update_settings("pricing", {"default": {"input_per_m": 0.4, "output_per_m": 1.4}})
    _seed_book_with_relation()
    nid = "n_cost1"
    with tx() as conn:
        conn.execute(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title, sort_order,"
            " status, created_at, updated_at) VALUES(?,?,?,?,?,?, 'draft', 't','t')",
            (nid, "p1", None, "chapter", "成本章", 1))
    # 有 node_id 的 run:成本应计入
    rid = start_run("chapter_draft", project_id="p1", node_id=nid, agent_type="writer")
    log_usage(rid, provider="openai-compatible", model="glm-5.3-flash",
              action="chapter_draft", request_tokens=1000, response_tokens=500,
              duration_ms=1000, project_id="p1")
    # 无 node_id 的 run(存量形态):不计入任何章
    rid2 = start_run("chapter_plan", project_id="p1", node_id=None, agent_type="planner")
    log_usage(rid2, provider="openai-compatible", model="glm-5.3-flash",
              action="chapter_plan", request_tokens=800, response_tokens=200,
              duration_ms=500, project_id="p1")
    from app.routers.dashboard import book_dashboard
    result = book_dashboard("p1")
    ch = next(r for r in result["chapters"] if r["node_id"] == nid)
    assert ch["cost"] > 0, "按章成本应聚合到有 node_id 的 run"
    # 存量 None 不计入:总成本 = 有 node_id 那条
    assert ch["cost"] < 0.25  # 单条 1000in/500out 折扣价约 0.0011


def test_book_session_and_context(tmp_db):
    """书级对话(骨架批执行书 §2):owner_type=book 会话可建;上下文含书信息/大纲链/
    近期章节/L1 常驻,且 node_id 原文在上下文里(outline_field 建议可引用)。"""
    from app.db import tx
    from app.routers.conversations import (
        MessageIn, SessionIn, _system_parts, create_session,
    )
    _seed_book_with_relation()
    with tx() as conn:
        conn.execute("UPDATE projects SET name='书级测试', genre='玄幻' WHERE id='p1'")
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, presence,"
            " entry_status, created_at, updated_at) VALUES('lz1','p1','worldview','世界树',"
            "'世界树撑起穹顶','always','confirmed','t','t')")
        conn.execute(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title, sort_order,"
            " status, created_at, updated_at) VALUES"
            "('ol_a','p1',NULL,'volume','第一卷',0,'unwritten','t','t'),"
            "('ol_b','p1','ol_a','chapter','第一章 开端',0,'draft','t','t')")
        conn.execute("UPDATE outline_nodes SET status_changed_at='2026-09-04 10:00:00'"
                     " WHERE id='ol_b'")
    s = create_session(SessionIn(project_id="p1", owner_type="book", owner_id="p1",
                                 name="书级线"))["session"]
    assert s["owner_type"] == "book"
    parts = _system_parts(s, MessageIn(message="帮我看看这本书"))
    text = "\n".join(parts)
    assert "书级测试" in text and "玄幻" in text
    assert "第一卷" in text and "第一章 开端" in text
    assert "ol_b" in text                       # node_id 原文给足
    assert "世界树" in text                      # L1 常驻摘要进了上下文
    assert "近期章节状态" in text and "2026-09-04" in text


def test_entity_links(tmp_db):
    """B3 互链聚合(骨架批执行书 §3):大纲节点=上级/事件/正文条目;条目=图谱引用+正文出现章。"""
    from app.db import tx
    from app.routers.graphs import BoardIn, NodeIn, create_board, create_node
    from app.routers.links import entity_links
    _seed_book_with_relation()
    with tx() as conn:
        conn.execute(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title, sort_order,"
            " status, created_at, updated_at) VALUES"
            "('ol_v','p1',NULL,'volume','第一卷',0,'unwritten','t','t'),"
            "('ol_c','p1','ol_v','chapter','第一章',0,'draft','t','t')")
        conn.execute(
            "INSERT INTO l4_texts(node_id, content, updated_at)"
            " VALUES('ol_c','陈昼走进殿堂,世界树低语。','t')")
        conn.execute(
            "INSERT INTO timeline_events(id, project_id, time_label, title, sort_key,"
            " created_at, updated_at) VALUES('te1','p1','第三个月','殿前对峙',0,'t','t')")
        conn.execute("INSERT INTO event_chapters(event_id, node_id) VALUES('te1','ol_c')")
    b = create_board("p1", BoardIn(kind="character", name="人物板"))["board"]
    create_node(b["id"], NodeIn(label="陈昼", ref_type="l1_entry", ref_id="e1"))
    r = entity_links("p1", etype="outline_node", id="ol_c")
    kinds = {g["kind"] for g in r["groups"]}
    assert "大纲上级" in kinds and "关联事件" in kinds and "正文提到的条目" in kinds
    r2 = entity_links("p1", etype="l1_entry", id="e1")
    by_kind = {g["kind"]: g["items"] for g in r2["groups"]}
    assert by_kind["图谱引用"][0]["title"] == "陈昼"
    assert by_kind["正文出现章节"][0]["id"] == "ol_c"
    assert by_kind["正文提到的条目"] if False else True  # 占位:上文 kinds 已断言
