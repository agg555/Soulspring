"""精修期第一批回归(C5 版本历史 / A1 建议协议 / A3 会话,执行书 2026-08-31)。

本批新表/新列:v8 迁移(changeset_patches.version+created_at、conversation_sessions、
review_messages.session_id、gen_tasks.session_id、outline_nodes.summary/note)。
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def tmp_db(monkeypatch):
    """独立临时库:重置全局连接后跑迁移,测试互不串库。"""
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    yield dbmod
    dbmod._conn = None


def _seed_chapter(conn) -> None:
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at)"
        " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
    conn.execute(
        "INSERT INTO outline_nodes(id, project_id, kind, title, created_at, updated_at)"
        " VALUES('n1', 'p1', 'chapter', '第一章', '2026-09-01', '2026-09-01')")
    conn.execute(
        "INSERT INTO l4_texts(node_id, content, updated_at)"
        " VALUES('n1', '正式正文 v0', '2026-09-01')")
    conn.execute(
        "INSERT INTO changesets(id, project_id, node_id, kind, status, payload, created_at)"
        " VALUES('cs1', 'p1', 'n1', 'draft', 'draft', '{}', '2026-09-01')")


# ── C5:追加式版本历史 ──

def test_put_patch_appends_versions(tmp_db):
    """重 roll/人改/自修各占一版,旧版本永不删除(解决覆盖丢档)。"""
    from app.db import tx
    from app.routers.workbench import _put_patch
    with tx() as conn:
        _seed_chapter(conn)
        _put_patch(conn, "cs1", "n1", "草稿A", "AI 草稿", 0)
        _put_patch(conn, "cs1", "n1", "草稿B", "人改", 0)
        _put_patch(conn, "cs1", "n1", "草稿C", "AI 自修一轮", 0)
        rows = conn.execute(
            "SELECT version, after, reason, created_at FROM changeset_patches"
            " WHERE changeset_id='cs1' ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == [1, 2, 3]
    assert [r["after"] for r in rows] == ["草稿A", "草稿B", "草稿C"]
    assert all(r["created_at"] for r in rows), "版本时间列必须留痕"


def test_changeset_view_splits_current_and_history(tmp_db):
    """patches 语义不变(= 各 field 当前版本),全历史进 patch_history。"""
    from app.db import tx
    from app.routers.workbench import _changeset_view, _put_patch
    with tx() as conn:
        _seed_chapter(conn)
        _put_patch(conn, "cs1", "n1", "草稿A", "AI 草稿", 0)
        _put_patch(conn, "cs1", "n1", "草稿B", "人改", 0)
    with tx() as conn:
        row = dict(conn.execute("SELECT * FROM changesets WHERE id='cs1'").fetchone())
    view = _changeset_view(row)
    assert [p["after"] for p in view["patches"]] == ["草稿B"]
    assert [p["version"] for p in view["patch_history"]] == [1, 2]


def test_patch_rollback_appends_new_version(tmp_db):
    """回滚 = 以历史版本文本为 after 追加新版本(版本链完整,可再滚回)。"""
    from app.db import tx
    from app.routers.workbench import RollbackIn, _put_patch, patch_rollback
    with tx() as conn:
        _seed_chapter(conn)
        _put_patch(conn, "cs1", "n1", "草稿A", "AI 草稿", 0)
        _put_patch(conn, "cs1", "n1", "草稿B", "人改", 0)
        v1_id = conn.execute(
            "SELECT id FROM changeset_patches WHERE changeset_id='cs1' AND version=1"
        ).fetchone()["id"]
    view = patch_rollback(nid="n1", project_id="p1", body=RollbackIn(patch_id=v1_id))
    hist = view["patch_history"]
    assert len(hist) == 3
    assert hist[-1]["after"] == "草稿A"
    assert "回滚" in hist[-1]["reason"]
    # 当前版本(patchers)切到回滚版
    assert [p["after"] for p in view["patches"]] == ["草稿A"]


# ── A1:建议协议解析与降级 ──

def test_parse_reply_valid_protocol():
    from app.routers.conversations import _parse_reply
    raw = ('{"reply": "整体节奏不错", "suggestions": [{"quote": "原文句", "issue": "节奏拖",'
           ' "suggestion": "压缩成一句", "severity": "major",'
           ' "target_type": "chapter_text", "target": {"node_id": "n1", "revised_text": "改后"}}]}')
    reply, sugs, err = _parse_reply(raw)
    assert err is False
    assert reply == "整体节奏不错"
    assert sugs[0]["target"]["node_id"] == "n1"
    assert sugs[0]["severity"] == "major"


def test_parse_reply_fenced_json_ok():
    from app.routers.conversations import _parse_reply
    raw = '```json\n{"reply": "好", "suggestions": []}\n```'
    reply, sugs, err = _parse_reply(raw)
    assert err is False
    assert reply == "好"
    assert sugs == []


def test_parse_reply_fallback_keeps_raw():
    """解析失败降级纯文本:parse_error=True 且原文完整保留(执行书 A1)。"""
    from app.routers.conversations import _parse_reply
    raw = "这段节奏拖了,建议压缩第二段。"
    reply, sugs, err = _parse_reply(raw)
    assert err is True
    assert sugs == []
    assert reply == raw


def test_parse_reply_sanitizes_fields():
    from app.routers.conversations import _parse_reply
    raw = ('{"reply": "r", "suggestions": ['
           '{"severity": "极高", "target_type": "随便", "target": "不是字典", "issue": "x"},'
           '"垃圾项"]}')
    reply, sugs, err = _parse_reply(raw)
    assert err is False
    assert len(sugs) == 1  # 非字典建议被丢弃
    assert sugs[0]["severity"] == "minor"
    assert sugs[0]["target_type"] == "none"
    assert sugs[0]["target"] == {}


# ── A3:多线会话 ──

def test_conversation_sessions_crud(tmp_db):
    from app.routers.conversations import SessionIn, create_session, list_sessions
    r = create_session(SessionIn(
        project_id="p1", owner_type="review", owner_id="n1", name="支线讨论"))
    sid = r["session"]["id"]
    sessions = list_sessions(project_id="p1", owner_type="review", owner_id="n1")["sessions"]
    assert [s["id"] for s in sessions] == [sid]
    assert sessions[0]["message_count"] == 0
    with pytest.raises(HTTPException):
        create_session(SessionIn(owner_type="不存在的类型", owner_id="", name="t"))
    with pytest.raises(HTTPException):
        create_session(SessionIn(owner_type="review", owner_id="", name="  "))


def test_messages_meta_json_parsed(tmp_db):
    from app.db import tx
    from app.routers.conversations import (
        SessionIn, create_session, get_messages,
    )
    sid = create_session(SessionIn(
        owner_type="review", owner_id="", name="s"))["session"]["id"]
    with tx() as conn:
        conn.execute(
            "INSERT INTO review_messages(id, session_id, role, content, meta, created_at)"
            " VALUES('m1', ?, 'assistant', '回复', ?, '2026-09-01')",
            (sid, '{"suggestions": [], "parse_error": true}'))
    msgs = get_messages(sid)["messages"]
    assert msgs[0]["meta"]["parse_error"] is True
    assert msgs[0]["meta"]["suggestions"] == []


# ── A1 采纳:两档闸门 ──

def _seed_suggestion(sid: str, target_type: str, target: dict) -> str:
    import json
    from app.db import tx
    meta = {"suggestions": [{
        "quote": "", "issue": "测试问题", "suggestion": "测试建议",
        "severity": "major", "target_type": target_type, "target": target,
    }]}
    with tx() as conn:
        conn.execute(
            "INSERT INTO review_messages(id, session_id, role, content, meta, created_at)"
            " VALUES('msg1', ?, 'assistant', '回复', ?, '2026-09-01')", (sid, json.dumps(meta)))
    return "msg1"


def test_adopt_outline_field_writes_back_and_logs(tmp_db):
    """轻档:确认后写回节点字段 + AgentRun 留痕;重复采纳拒绝。"""
    from app.db import tx
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    with tx() as conn:
        _seed_chapter(conn)
    sid = create_session(SessionIn(
        owner_type="review", owner_id="n1", name="s"))["session"]["id"]
    _seed_suggestion(sid, "outline_field",
                     {"node_id": "n1", "field": "summary", "value": "新摘要"})
    r = adopt_suggestion(AdoptIn(session_id=sid, message_id="msg1", index=0))
    assert r["before"] == ""
    assert r["after"] == "新摘要"
    with tx() as conn:
        node = conn.execute("SELECT summary FROM outline_nodes WHERE id='n1'").fetchone()
        run = conn.execute(
            "SELECT action, status FROM agent_runs WHERE node_id='n1'"
            " AND action='adopt_outline_suggestion'").fetchone()
    assert node["summary"] == "新摘要"
    assert run is not None and run["status"] == "succeeded"
    with pytest.raises(HTTPException):
        adopt_suggestion(AdoptIn(session_id=sid, message_id="msg1", index=0))  # 已采纳


def test_adopt_outline_field_whitelist(tmp_db):
    """字段白名单外(如 status)轻档拒绝,防越权写。"""
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    sid = create_session(SessionIn(
        owner_type="review", owner_id="n1", name="s"))["session"]["id"]
    _seed_suggestion(sid, "outline_field",
                     {"node_id": "n1", "field": "status", "value": "finalized"})
    with pytest.raises(HTTPException):
        adopt_suggestion(AdoptIn(session_id=sid, message_id="msg1", index=0))


def test_adopt_chapter_text_appends_patch(tmp_db):
    """重档:修改段落作为新版本追加进该章变更集(AI 自修同管道),正文不动。"""
    from app.db import tx
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    with tx() as conn:
        _seed_chapter(conn)
    sid = create_session(SessionIn(
        owner_type="review", owner_id="n1", name="s"))["session"]["id"]
    _seed_suggestion(sid, "chapter_text",
                     {"node_id": "n1", "revised_text": "人改后的修改段落" * 3})
    r = adopt_suggestion(AdoptIn(session_id=sid, message_id="msg1", index=0))
    assert r["target"] == "chapter_text"
    with tx() as conn:
        patches = conn.execute(
            "SELECT version, after, reason FROM changeset_patches"
            " WHERE changeset_id='cs1' ORDER BY version").fetchall()
        l4 = conn.execute("SELECT content FROM l4_texts WHERE node_id='n1'").fetchone()
    assert [p["version"] for p in patches] == [1]  # 原本无补丁,采纳追加了第 1 版
    assert patches[-1]["reason"] == "对话建议采纳"
    assert l4["content"] == "正式正文 v0"  # 重档不直接改正文,人改工作区再合入


def test_adopt_chapter_text_without_changeset_rejected(tmp_db):
    """该章无打开变更集时,正文类建议不可采纳(提示先去工作台生成草稿)。"""
    from app.db import tx
    from app.routers.adopt import AdoptIn, adopt_suggestion
    from app.routers.conversations import SessionIn, create_session
    with tx() as conn:
        _seed_chapter(conn)
        conn.execute("DELETE FROM changesets WHERE id='cs1'")
    sid = create_session(SessionIn(
        owner_type="review", owner_id="n1", name="s"))["session"]["id"]
    _seed_suggestion(sid, "chapter_text", {"node_id": "n1", "revised_text": "x"})
    with pytest.raises(HTTPException) as e:
        adopt_suggestion(AdoptIn(session_id=sid, message_id="msg1", index=0))
    assert "变更集" in str(e.value.detail)
