"""二期③:章节信息卡回归(四行直写既有表 + 消费者 a 装配注入 + b 体检新规)。

判据对齐:四行直写落库正确/装配注入生效/体检新规抓真问题/零 L1·L2 直写/
有场景的章返回场景聚合引导。
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.assembly import build_assembly  # noqa: E402
from app.db import tx  # noqa: E402
from app.routers.chapter_card import CardIn, get_card, save_card  # noqa: E402
from app.routers.diagnostics import algorithm_check  # noqa: E402


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    with tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO outline_nodes(id, project_id, kind, title,"
                     " created_at, updated_at)"
                     " VALUES('n1', 'p1', 'chapter', '第3章 风起',"
                     " '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO graph_boards(id, project_id, kind, name, grid_on,"
                     " created_at, updated_at)"
                     " VALUES('gb1', 'p1', 'character', '人物关系', 1,"
                     " '2026-09-01', '2026-09-01')")
        # 两个已有人物节点(ref 到 L1 角色)
        conn.execute("INSERT INTO l1_entries(id, project_id, category, name, content,"
                     " entry_status, presence, created_at, updated_at)"
                     " VALUES('e1', 'p1', 'character', '林凡', '主角档案',"
                     " 'confirmed', 'on_demand', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO l1_entries(id, project_id, category, name, content,"
                     " entry_status, presence, created_at, updated_at)"
                     " VALUES('e2', 'p1', 'character', '苏晴', '女主档案',"
                     " 'confirmed', 'on_demand', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label,"
                     " x, y, style, created_at, updated_at)"
                     " VALUES('gn1', 'gb1', 'l1_entry', 'e1', '林凡', 10, 10,"
                     " '{}', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label,"
                     " x, y, style, created_at, updated_at)"
                     " VALUES('gn2', 'gb1', 'l1_entry', 'e2', '苏晴', 60, 60,"
                     " '{}', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO timeline_events(id, project_id, title, line,"
                     " status, sort_key, created_at, updated_at)"
                     " VALUES('ev1', 'p1', '风起事件', '主线', '已定', 1,"
                     " '2026-09-01', '2026-09-01')")
        # 本章正文:提到"苏晴"(供体检"未登场先用"测试)
        conn.execute("INSERT INTO l4_texts(node_id, content, updated_at)"
                     " VALUES('n1', '林凡与苏晴在码头相遇。', '2026-09-01')")
    yield dbmod
    dbmod._conn = None


def test_summary_note_write_and_read(tmp_db):
    save_card("n1", "p1", CardIn(summary="码头相遇,埋下线索", note="注意雨景"))
    card = get_card("n1", "p1")
    assert card["summary"] == "码头相遇,埋下线索"
    assert card["note"] == "注意雨景"
    assert card["chapter_no"] == 3


def test_event_link_diff_sync(tmp_db):
    save_card("n1", "p1", CardIn(event_ids=["ev1"]))
    assert get_card("n1", "p1")["linked_event_ids"] == ["ev1"]
    save_card("n1", "p1", CardIn(event_ids=[]))
    assert get_card("n1", "p1")["linked_event_ids"] == []


def test_cast_star_edges_and_consumers(tmp_db):
    # 选两人 → 一条星形同框边(at_chapter=3)
    save_card("n1", "p1", CardIn(cast_node_ids=["gn1", "gn2"]))
    card = get_card("n1", "p1")
    assert set(card["cast_node_ids"]) == {"gn1", "gn2"}
    with tx() as conn:
        edges = [dict(r) for r in conn.execute("SELECT * FROM graph_edges")]
    assert len(edges) == 1 and edges[0]["kind"] == "同框"
    import json
    assert json.loads(edges[0]["style"])["at_chapter"] == 3
    # 消费者 a:计划卡只提林凡 → 苏晴的按需条目不装配;cast 注入把它救回
    with tx() as conn:
        conn.execute("INSERT INTO chapter_plans(node_id, plan, updated_at)"
                     " VALUES('n1', '{\"focus\": \"林凡\"}', '2026-09-01')")
    asm = build_assembly("p1", "n1", log=False)
    by_src = {(s["source"], s["title"]): s for s in asm["sections"]}
    assert by_src[("l1:character", "苏晴")]["included"] is False          # 计划卡漏掉
    assert ("l1:cast", "本章人物·苏晴") in by_src                        # cast 救回
    assert by_src[("l1:cast", "本章人物·苏晴")]["included"] is True
    # 拆人:重建语义;单人=422 指引走场景卡(原 cast 不动)
    save_card("n1", "p1", CardIn(cast_node_ids=[]))
    assert get_card("n1", "p1")["cast_node_ids"] == []      # 清空合法
    save_card("n1", "p1", CardIn(cast_node_ids=["gn1", "gn2"]))
    with pytest.raises(HTTPException, match="至少选 2"):
        save_card("n1", "p1", CardIn(cast_node_ids=["gn1"]))
    assert set(get_card("n1", "p1")["cast_node_ids"]) == {"gn1", "gn2"}


def test_diagnostics_catch_early_use_and_mismatch(tmp_db):
    # 消费者 b:先标"登场第5章",再体检第3章正文已出现 → 抓到
    with tx() as conn:
        conn.execute(
            "INSERT INTO graph_edges(id, board_id, from_node_id, to_node_id, label,"
            " kind, style, created_at, updated_at)"
            " VALUES('ge_d', 'gb1', 'gn2', 'gn2', '', '同框',"
            " '{\"at_chapter\": 5}', '2026-09-01', '2026-09-01')")
        # 名字不一:gn1 标签改成与档案名不同
        conn.execute("UPDATE graph_nodes SET label='林凡(青年)' WHERE id='gn1'")
    r = algorithm_check("p1")
    checks = {c["key"]: c for c in r["checks"]}
    assert checks["cast_early_use"]["count"] >= 1
    item = checks["cast_early_use"]["items"][0]
    assert item["node_id"] == "n1" and "苏晴" in item["detail"]
    assert checks["cast_name_mismatch"]["count"] >= 1
    assert "林凡(青年)" in checks["cast_name_mismatch"]["items"][0]["detail"]


def test_no_leak_into_l1(tmp_db):
    """红线:信息卡零 L1 直写(保存前后 L1 条目内容不变)。"""
    save_card("n1", "p1", CardIn(summary="s", note="n", cast_node_ids=["gn1", "gn2"]))
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT name, content FROM l1_entries WHERE project_id='p1'")]
    assert rows == [{"name": "林凡", "content": "主角档案"},
                    {"name": "苏晴", "content": "女主档案"}]
