"""上下文经济(批次三⑤)回归:历史全量/失忆bug修复/压缩与装配裁剪/思考关档映射。"""
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


from app.ledger.usage import _apply_thinking  # noqa: E402
from app.routers.conversations import (  # noqa: E402
    COMPACT_KEEP,
    CompactIn,
    _assembly_history,
    _compact_session,
    _get_session,
    _history,
    _system_parts,
    compact_session,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_session(dbmod, name: str = "经济线") -> str:
    sid = f"conv_{uuid.uuid4().hex[:16]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO conversation_sessions(id, owner_type, name, created_at)"
            " VALUES(?,?,?,?)", (sid, "chat_test", name, _now()))
    return sid


def _mk_msg(dbmod, sid: str, role: str, content: str, seq: int) -> None:
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO review_messages(id, project_id, session_id, role, content,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (f"rev_{uuid.uuid4().hex[:16]}", "", sid, role, content,
             f"2026-09-06T00:{seq:02d}:00+00:00"))


def test_history_full_not_first40(tmp_db):
    """失忆 bug 回归:旧实现升序 LIMIT 40 只见开头;现必须全量且按时间序。"""
    sid = _mk_session(tmp_db)
    for i in range(45):
        _mk_msg(tmp_db, sid, "user" if i % 2 == 0 else "assistant", f"消息{i}", i)
    hist = _history(sid)
    assert len(hist) == 45
    assert hist[0]["content"] == "消息0" and hist[-1]["content"] == "消息44"


def test_compact_and_assembly(tmp_db):
    sid = _mk_session(tmp_db)
    for i in range(20):
        _mk_msg(tmp_db, sid, "user" if i % 2 == 0 else "assistant", f"消息{i} " + "内容" * 50, i)
    # 无摘要=全量装配
    session = _get_session(sid)
    assert len(_assembly_history(session)) == 20
    # 压缩:最近 5 条保留,更早 15 条入提要;原文全留库
    info = _compact_session(sid, keep=5)
    assert info["compacted"] == 15
    session = _get_session(sid)
    assert "前情提要" in (session["digest"] or "")
    assert len(_assembly_history(session)) == COMPACT_KEEP
    hist = _history(sid)
    assert len(hist) == 20   # 原始消息不删
    # 再压缩=增量追加,不重置
    for i in range(20, 24):
        _mk_msg(tmp_db, sid, "user", f"消息{i}", i)
    info2 = _compact_session(sid, keep=5)
    assert info2["compacted"] > 0
    assert _get_session(sid)["digest"].count("前情提要") >= 1


def test_compact_short_line_noop_and_404(tmp_db):
    sid = _mk_session(tmp_db)
    _mk_msg(tmp_db, sid, "user", "只有一条", 0)
    result = compact_session(sid, CompactIn(keep=16))
    assert result["compacted"] == 0 and "无需压缩" in result["message"]
    with pytest.raises(Exception):
        compact_session("conv_nosuch", CompactIn(keep=16))


def test_system_parts_injects_digest(tmp_db):
    sid = _mk_session(tmp_db)
    with tmp_db.tx() as conn:
        conn.execute("UPDATE conversation_sessions SET digest=? WHERE id=?",
                     ("【前情提要】\n- 我: 开头设定", sid))
    session = _get_session(sid)
    parts = _system_parts(session, type("B", (), {"attachments": [], "ref_prompt_ids": None, "preset_text": None, "preset": None})())
    assert any("前情提要" in p for p in parts)
    assert any("回复" in p or "JSON" in p for p in parts)   # 协议仍在提要之后


def test_apply_thinking_off_and_levels():
    """关档映射:DeepSeek=显式 disabled;GLM 强制思考不可关→回落动作默认档。"""
    eb: dict = {}
    _apply_thinking(eb, "off", "chat_test", "deepseek-v4-flash")
    assert eb["thinking"] == {"type": "disabled"}
    eb = {}
    _apply_thinking(eb, "off", "chat_test", "glm-5.3-flash")
    assert "thinking" not in eb
    # 终审修复:解析不出档位(总开关关)时不得写入 null 参数
    assert eb.get("reasoning_effort") in ("low", "high", "max")
    assert None not in eb.values()
    eb = {}
    _apply_thinking(eb, "high", "chat_test", "deepseek-v4-flash")
    assert eb["thinking"] == {"type": "enabled"}
    eb = {}
    _apply_thinking(eb, "high", "chat_test", "glm-5.3-flash")
    assert eb.get("reasoning_effort") == "high"
    eb = {}
    _apply_thinking(eb, None, "chat_test", "deepseek-v4-flash")
    assert eb == {}
