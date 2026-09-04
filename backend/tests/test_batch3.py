"""第三批回归(码字埋点/驾驶舱分值/时间线/关系图/新采纳,任务词 2026-09-01)。"""
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


def _seed_chapter_with_cs(conn):
    """项目 + 章 + 打开的变更集;返回 (pid, nid, cs_id)。"""
    pid, nid = "p1", "n1"
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at)"
        " VALUES(?, '测试书', '2026-09-01', '2026-09-01')", (pid,))
    conn.execute(
        "INSERT INTO outline_nodes(id, project_id, kind, title, created_at, updated_at)"
        " VALUES(?, ?, 'chapter', '第一章', '2026-09-01', '2026-09-01')", (nid, pid))
    conn.execute(
        "INSERT INTO changesets(id, project_id, node_id, kind, status, payload, created_at)"
        " VALUES('cs1', ?, ?, 'draft', 'draft', '{}', '2026-09-01')", (pid, nid))
    return pid, nid, "cs1"


# ── 码字埋点(B1)──

def test_put_patch_word_count_sources(tmp_db):
    """human/ai 记 delta 与 words_after;回滚(source=None)不记。"""
    from app.db import tx
    from app.routers.workbench import _put_patch
    with tx() as conn:
        _seed_chapter_with_cs(conn)
        _put_patch(conn, "cs1", "n1", "草稿A"*10, "AI 草稿", 0, source="ai")
        _put_patch(conn, "cs1", "n1", "草稿A"*10 + "人改增补", "人改", 0, source="human")
        _put_patch(conn, "cs1", "n1", "草稿A"*10, "回滚到 v1", 0)  # 回滚不记
        rows = conn.execute(
            "SELECT source, delta, words_after FROM word_count_log"
            " ORDER BY created_at, rowid").fetchall()
    assert [(r["source"], r["delta"]) for r in rows] == [
        ("ai", 30), ("human", 4)]
    assert all(r["words_after"] > 0 for r in rows)


def test_word_stats_aggregation(tmp_db):
    """word-stats:今日人工/AI 分列;chapter 维度聚合。"""
    from datetime import datetime, timezone

    from app.db import tx
    from app.routers.dashboard import word_stats
    # 今日桶断言要求落库时间在"今天":用当前 UTC 日期动态生成,跨天不碎
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
    with tx() as conn:
        _seed_chapter_with_cs(conn)
        for src, delta in (("human", 100), ("human", -20), ("ai", 500)):
            conn.execute(
                "INSERT INTO word_count_log(id, project_id, node_id, source, delta,"
                " words_after, created_at) VALUES(?,?,?,?,?,?,?)",
                (f"wc_{src}{delta}", "p1", "n1", src, delta, 0, now))
    s = word_stats("p1", node_id="n1")
    assert s["today"]["human"] == 80       # 净增(负增量也计)
    assert s["today"]["ai"] == 500
    assert s["chapter"]["human"] == 80


# ── B4 分值合成 ──

def test_dashboard_quality_scores(tmp_db):
    """评审均分+朱雀+成本加权和;critical 一票否决仅展示;权重可调。"""
    from app.db import tx
    from app.routers.dashboard import WeightsIn, book_dashboard, put_dashboard_weights
    with tx() as conn:
        _seed_chapter_with_cs(conn)
        conn.execute(
            "UPDATE changesets SET validations=?, review=? WHERE id='cs1'",
            (json.dumps([{"status": "warning", "message": "x"}]),
             json.dumps({"scores": {"情节": {"score": 8}, "节奏": {"score": 6}}})))
        conn.execute(
            "INSERT INTO agent_runs(id, project_id, node_id, action, agent_type, status,"
            " created_at) VALUES('r1','p1','n1','chapter_draft','writer','succeeded','2026-09-01')")
        conn.execute(
            "INSERT INTO ai_usage_logs(id, run_id, project_id, model, action, cost_total,"
            " created_at) VALUES('u1','r1','p1','m','chapter_draft',0.1,'2026-09-01')")
        conn.execute(
            "INSERT INTO zhuque_log(id, project_id, node_id, verdict, human_ratio, created_at)"
            " VALUES('z1','p1','n1','人工',0.9,'2026-09-01')")
    d = book_dashboard("p1")
    row = d["chapters"][0]
    q = row["quality"]
    assert q["review_score"] == 7.0
    assert q["zhuque_score"] == 9.0
    # 默认权重 0.5/0.3/0.2,成本 0.1/0.25 → cost_score=6 → (7*0.5+9*0.3+6*0.2)/1.0=7.4
    assert q["score"] == 7.4
    put_dashboard_weights("p1", WeightsIn(w_review=1.0, w_zhuque=0.0, w_cost=0.0))
    d2 = book_dashboard("p1")
    assert d2["chapters"][0]["quality"]["score"] == 7.0   # 权重改后重算生效
    # 一票否决:加一条未豁免 critical
    with tx() as conn:
        conn.execute(
            "UPDATE changesets SET validations=? WHERE id='cs1'",
            (json.dumps([{"status": "failed", "message": "dead char"}]),))
    d3 = book_dashboard("p1")
    assert d3["chapters"][0]["quality"]["veto"] is True
    assert d3["chapters"][0]["quality"]["score"] is None


# ── B2 生产时间线端点(status_label 列踩坑三次,端点级回归)──

def test_production_timeline_aggregates(tmp_db):
    """补丁/任务/状态日志按时序聚合;响应含 status_label 应用层映射。"""
    from app.db import tx
    from app.routers.dashboard import production_timeline
    from app.routers.workbench import _put_patch
    with tx() as conn:
        pid, nid, cs = _seed_chapter_with_cs(conn)
        _put_patch(conn, cs, nid, "正文" * 100, "AI 草稿", 0, source="ai")
    r = production_timeline(nid, pid)
    kinds = [e["kind"] for e in r["events"]]
    assert any(k.startswith("补丁") for k in kinds)
    assert r["node"]["status_label"] in ("未写", "草稿", "人改中", "待终审", "定稿")

# ── C 剧情时间线 ──

def test_timeline_event_lifecycle(tmp_db):
    """建事件→挂章→改字段→删章清关联→删事件清关联。"""
    from app.db import tx
    from app.routers.dashboard import (
        EventChapterIn, EventIn, EventPatch, create_event, delete_event, link_chapter,
        list_events, unlink_chapter, update_event,
    )
    from app.routers.outline import NodeIn, create_node, delete_node
    with tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at)"
            " VALUES('p1','测试书','2026-09-01','2026-09-01')")
    ch = create_node("p1", NodeIn(kind="category", parent_id=None, title="总纲"))["id"]
    ch2 = create_node("p1", NodeIn(kind="volume", parent_id=ch, title="卷"))["id"]
    evt = create_event("p1", EventIn(time_label="第三个月", title="残纸现世",
                                     line="主线", status="未定"))["event"]
    assert evt["sort_key"] == 1
    link_chapter(evt["id"], EventChapterIn(node_id=ch2))
    update_event(evt["id"], EventPatch(status="已定"))
    rows = list_events("p1")["events"]
    assert rows[0]["status"] == "已定" and rows[0]["chapters"][0]["id"] == ch2
    # 删章 → 关联清理
    delete_node(ch2)
    assert list_events("p1")["events"][0]["chapters"] == []
    # 删事件 → event_chapters 清(此处空,验证端点不炸)
    delete_event(evt["id"])
    assert list_events("p1")["events"] == []


# ── D 角色关系 ──
# S10(a) 2026-09-01:旧表写端点下线,原 CRUD/删角色级联测试随功能删除
# (只读 list_relations 保留;关系维护走统一图谱引擎,见 test_batch4 图谱用例)


# ── E:事件字段轻档采纳 ──

def _seed_suggestion(sid: str, target_type: str, target: dict, msg_id: str = "msg1") -> str:
    import json as _json
    from app.db import tx
    meta = {"suggestions": [{
        "quote": "", "issue": "x", "suggestion": "y", "severity": "major",
        "target_type": target_type, "target": target,
    }]}
    with tx() as conn:
        conn.execute(
            "INSERT INTO review_messages(id, session_id, role, content, meta, created_at)"
            " VALUES(?, ?, 'assistant', 'r', ?, 't')", (msg_id, sid, _json.dumps(meta)))
    return msg_id


def test_adopt_event_field(tmp_db):
    """event_field 轻档:写回+outline_field_history(node_type 区分)。

    relation_field 采纳随旧表写端点一并下线(S10(a),2026-09-01),相关断言删除。
    """
    from app.db import tx
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    from app.routers.dashboard import EventIn, create_event
    with tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at)"
            " VALUES('p1','测试书','2026-09-01','2026-09-01')")
    evt = create_event("p1", EventIn(title="残纸现世"))["event"]
    sid = create_session(SessionIn(
        owner_type="timeline_event", owner_id=evt["id"], name="s"))["session"]["id"]
    msg = _seed_suggestion(sid, "event_field",
                           {"event_id": evt["id"], "field": "status", "value": "已定"})
    r = adopt_suggestion(AdoptIn(session_id=sid, message_id=msg, index=0))
    assert r["after"] == "已定"
    with tx() as conn:
        row = conn.execute(
            "SELECT status FROM timeline_events WHERE id=?", (evt["id"],)).fetchone()
        hist = conn.execute(
            "SELECT node_type, field, before FROM outline_field_history"
            " WHERE node_id=?", (evt["id"],)).fetchone()
    assert row["status"] == "已定"
    assert hist["node_type"] == "event" and hist["field"] == "status"
    # 非法值拒绝(line 只能主线/支线)
    msg3 = _seed_suggestion(sid, "event_field",
                            {"event_id": evt["id"], "field": "line", "value": "支线外"},
                            msg_id="msg3")
    with pytest.raises(HTTPException):
        adopt_suggestion(AdoptIn(session_id=sid, message_id=msg3, index=0))
