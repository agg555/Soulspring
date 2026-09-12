"""算法体检六项回归(批次三②,2026-09-06):坏数据逐项命中/干净数据零误报/隔离项不误报。"""
import json
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


from app.routers.diagnostics import algorithm_check  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_project(dbmod, name: str) -> str:
    pid = f"proj_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at) VALUES(?,?,?,?)",
            (pid, name, _now(), _now()))
    return pid


def _mk_node(dbmod, pid: str, kind: str, title: str,
             parent_id: str | None = None) -> str:
    nid = f"on_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (nid, pid, parent_id, kind, title, _now(), _now()))
    return nid


def _mk_hook_node(dbmod, pid: str, status: str | None) -> str:
    bid = f"gb_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO graph_boards(id, project_id, kind, name, created_at,"
            " updated_at) VALUES(?,?,?,?,?,?)",
            (bid, pid, "hook", "伏笔流转板", _now(), _now()))
    nid = f"gn_{uuid.uuid4().hex[:12]}"
    style = json.dumps({"status": status}, ensure_ascii=False) if status else "{}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO graph_nodes(id, board_id, label, style, created_at,"
            " updated_at) VALUES(?,?,?,?,?,?)",
            (nid, bid, f"钩子-{status or '默认'}", style, _now(), _now()))
    return nid


def _mk_l1(dbmod, pid: str, category: str, name: str,
           entry_status: str = "confirmed") -> str:
    eid = f"l1_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content,"
            " entry_status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (eid, pid, category, name, "内容", entry_status, _now(), _now()))
    return eid


def _mk_event(dbmod, pid: str, title: str, line: str, sort_key: int,
              time_label: str = "") -> str:
    eid = f"ev_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO timeline_events(id, project_id, time_label, title,"
            " line, sort_key, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (eid, pid, time_label, title, line, sort_key, _now(), _now()))
    return eid


def _items(checks: list[dict], key: str) -> list[dict]:
    return next(c for c in checks if c["key"] == key)["items"]


def test_clean_book_zero_issues(tmp_db):
    pid = _mk_project(tmp_db, "干净书")
    vol = _mk_node(tmp_db, pid, "volume", "第一卷")
    for i in range(3):
        _mk_node(tmp_db, pid, "chapter", f"第{i + 1}章", vol)
    _mk_hook_node(tmp_db, pid, "回收")
    _mk_l1(tmp_db, pid, "character", "林晚")
    _mk_event(tmp_db, pid, "开幕", "主线", 1, time_label="第一天")
    result = algorithm_check(pid)
    assert result["total_issues"] == 0, result["checks"]


def test_orphan_chapter_and_lonely_volume(tmp_db):
    pid = _mk_project(tmp_db, "坏结构书")
    _mk_node(tmp_db, pid, "chapter", "断头章")  # 无父→命中
    # 父挂在大纲大类(总纲)下=父类型异常→命中;父节点物理缺失被 FK 挡死,不可能出现
    cat = _mk_node(tmp_db, pid, "category", "余期正传")
    _mk_node(tmp_db, pid, "chapter", "挂错父章", cat)
    vol_empty = _mk_node(tmp_db, pid, "volume", "空卷")  # 下无章→命中
    vol_ok = _mk_node(tmp_db, pid, "volume", "正常卷")
    _mk_node(tmp_db, pid, "chapter", "第一章", vol_ok)
    checks = algorithm_check(pid)["checks"]
    assert {"断头章", "挂错父章"} <= {i["title"] for i in _items(checks, "orphan_chapter")}
    assert {i["node_id"] for i in _items(checks, "lonely_volume")} == {vol_empty}


def test_dense_volume_over_threshold(tmp_db):
    pid = _mk_project(tmp_db, "章海书")
    vol = _mk_node(tmp_db, pid, "volume", "爆仓卷")
    for i in range(19):  # 阈值 18,19 章必中
        _mk_node(tmp_db, pid, "chapter", f"第{i + 1}章", vol)
    items = _items(algorithm_check(pid)["checks"], "dense_parent")
    assert len(items) == 1 and "19 章" in items[0]["detail"]


def test_hook_open_vs_recovered(tmp_db):
    pid = _mk_project(tmp_db, "伏笔书")
    _mk_hook_node(tmp_db, pid, "埋设")
    _mk_hook_node(tmp_db, pid, "强化")
    _mk_hook_node(tmp_db, pid, "回收")   # 闭环不算
    _mk_hook_node(tmp_db, pid, None)     # 默认=埋设,算未回收
    items = _items(algorithm_check(pid)["checks"], "hook_open")
    assert len(items) == 3
    assert all("回收" not in i["title"] for i in items)


def test_dup_entry_same_category_only_confirmed(tmp_db):
    pid = _mk_project(tmp_db, "重名书")
    first = _mk_l1(tmp_db, pid, "character", "林晚")
    dup = _mk_l1(tmp_db, pid, "character", " 林晚 ")      # 去空格后同名→二选一命中
    _mk_l1(tmp_db, pid, "map", "林晚")                    # 不同分类→不命中
    _mk_l1(tmp_db, pid, "character", "林晚", "proposal")  # 提案→不命中
    items = _items(algorithm_check(pid)["checks"], "dup_entry")
    assert len(items) == 1 and items[0]["node_id"] in {first, dup}
    assert "同名" in items[0]["detail"]


def test_graph_overview_aggregates_all_boards(tmp_db):
    """批次三⑥总览:多板节点/边全聚合,空书零计数。"""
    from app.routers.diagnostics import graph_overview
    pid = _mk_project(tmp_db, "总览书")
    empty = graph_overview(pid)
    assert empty["board_count"] == 0 and empty["node_count"] == 0
    bid = f"gb_{uuid.uuid4().hex[:12]}"
    with tmp_db.tx() as conn:
        conn.execute(
            "INSERT INTO graph_boards(id, project_id, kind, name, created_at,"
            " updated_at) VALUES(?,?,?,?,?,?)",
            (bid, pid, "hook", "伏笔板", _now(), _now()))
        conn.execute(
            "INSERT INTO graph_nodes(id, board_id, label, x, y, style,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (f"gn_{uuid.uuid4().hex[:12]}", bid, "残纸现世", 10, 20,
             "{}", _now(), _now()))
    result = graph_overview(pid)
    assert result["board_count"] == 1 and result["node_count"] == 1
    board = result["boards"][0]
    assert board["kind"] == "hook"
    assert board["nodes"][0]["label"] == "残纸现世"
    assert board["nodes"][0]["category"] == "free"  # 类别派生与单板同源


def test_timeline_conflicts(tmp_db):
    pid = _mk_project(tmp_db, "时序书")
    _mk_event(tmp_db, pid, "事件甲", "主线", 5, time_label="第一天")
    same_key = _mk_event(tmp_db, pid, "事件乙", "主线", 5, time_label="第一天")  # 同线同键→冲突
    other_line = _mk_event(tmp_db, pid, "事件丙", "支线", 5, time_label="第一天")  # 异线同键→不冲突
    _mk_event(tmp_db, pid, "漂流事件", "主线", 9)  # 无标签无关联→缺时间锚
    items = _items(algorithm_check(pid)["checks"], "timeline_conflict")
    hit_ids = {i["node_id"] for i in items}
    assert same_key in hit_ids and other_line not in hit_ids
    assert "排序键相同" in next(i["detail"] for i in items if i["node_id"] == same_key)
    assert {i["title"] for i in items} >= {"漂流事件"}
