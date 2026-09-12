"""批次七⑤:构思树回归(下钻/深度≤3/三态/冻结不喂 AI/层叠摘要/书级待议注入)。

判据对齐执行书附节:下钻开子线(会话挂 idea)/转正写回走闸门(ideas 路由无
任何直写大纲/正文/图谱的通道)/深度限制/层叠摘要可见/默认零配置行为不变。
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.assembly import build_book_context  # noqa: E402
from app.db import tx  # noqa: E402
from app.routers.conversations import (  # noqa: E402
    SessionIn, create_session, _system_parts,
)
from app.routers.ideas import (  # noqa: E402
    IdeaIn, PatchIn, chain_for_context, create_idea, delete_idea, latest_parent_digest,
    list_ideas, patch_idea,
)


class MsgIn:
    """_context_* 的 body 替身(只用 preset/preset_text/ref_prompt_ids/attachments 字段)。"""
    preset = None
    preset_text = None
    ref_prompt_ids = None
    attachments = []


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
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p2', '另一本', '2026-09-01', '2026-09-01')")
    yield dbmod
    dbmod._conn = None


def _mk_idea(**kw) -> dict:
    body = IdeaIn(pid="p1", title=kw.pop("title"), **kw)
    return create_idea(body)["idea"]


def test_depth_chain_and_limit(tmp_db):
    root = _mk_idea(title="主角换个金手指", note="讨论主线")
    child = _mk_idea(title="子线:能力代价", parent_idea_id=root["id"])
    grand = _mk_idea(title="孙线:代价具象化", parent_idea_id=child["id"])
    assert (root["depth"], child["depth"], grand["depth"]) == (1, 2, 3)
    with pytest.raises(HTTPException, match="最大深度"):
        create_idea(IdeaIn(pid="p1", title="第四层", parent_idea_id=grand["id"]))
    # 兄弟不受影响:同一父下再挂仍是 depth 3
    grand2 = _mk_idea(title="孙线B", parent_idea_id=child["id"])
    assert grand2["depth"] == 3


def test_create_under_dropped_parent_blocked(tmp_db):
    root = _mk_idea(title="被放弃的方向")
    patch_idea(root["id"], PatchIn(status="dropped"))
    with pytest.raises(HTTPException, match="冻结"):
        create_idea(IdeaIn(pid="p1", title="还想继续", parent_idea_id=root["id"]))


def test_cross_book_parent_rejected(tmp_db):
    root = _mk_idea(title="p1 的构思")
    with pytest.raises(HTTPException, match="不属于这本书"):
        create_idea(IdeaIn(pid="p2", title="p2 的子构思", parent_idea_id=root["id"]))


def test_status_transitions_and_validation(tmp_db):
    idea = _mk_idea(title="三态流转")
    assert patch_idea(idea["id"], PatchIn(status="adopted"))["idea"]["status"] == "adopted"
    assert patch_idea(idea["id"], PatchIn(status="open"))["idea"]["status"] == "open"
    assert patch_idea(idea["id"], PatchIn(status="dropped"))["idea"]["status"] == "dropped"
    with pytest.raises(HTTPException, match="非法状态"):
        patch_idea(idea["id"], PatchIn(status="deleted"))


def test_delete_cascades_subtree(tmp_db):
    root = _mk_idea(title="根")
    child = _mk_idea(title="子", parent_idea_id=root["id"])
    grand = _mk_idea(title="孙", parent_idea_id=child["id"])
    other = _mk_idea(title="别家的")
    r = delete_idea(root["id"])
    assert r["deleted"] == 3
    left = [i["title"] for i in list_ideas("p1")["ideas"]]
    assert left == ["别家的"] and grand["id"] not in left


def test_source_ref_roundtrip(tmp_db):
    idea = _mk_idea(title="来自建议", source_ref={"session_id": "s1", "message_id": "m1", "idx": 2})
    got = list_ideas("p1")["ideas"][0]
    assert got["source_ref"] == {"session_id": "s1", "message_id": "m1", "idx": 2}


def test_idea_session_context_chain_and_digest(tmp_db):
    root = _mk_idea(title="主线重构", note="书级大方向")
    child = _mk_idea(title="子线:视角收束", parent_idea_id=root["id"])
    # 父层历史线的 digest(纯算法提要,批次三⑤形态)
    sess_root = create_session(SessionIn(project_id="p1", owner_type="idea",
                                         owner_id=root["id"], name="父线讨论"))["session"]
    with tx() as conn:
        conn.execute("UPDATE conversation_sessions SET digest=? WHERE id=?",
                     ("前情:作者倾向第一人称收束。", sess_root["id"]))
    session = create_session(SessionIn(project_id="p1", owner_type="idea",
                                       owner_id=child["id"], name="子线讨论"))["session"]
    parts = _system_parts(dict(session), MsgIn())
    idea_part = next(p for p in parts if p.startswith("## 构思树·父链"))
    assert "主线重构[待议]:书级大方向" in idea_part
    assert "该层前情提要:前情:作者倾向第一人称收束。" in idea_part   # 层叠摘要可见(判据)
    assert "▸ 本线 子线:视角收束" in idea_part


def test_frozen_idea_context_raises_before_llm(tmp_db):
    root = _mk_idea(title="冻结根")
    child = _mk_idea(title="冻结子", parent_idea_id=root["id"])
    patch_idea(root["id"], PatchIn(status="dropped"))
    session = create_session(SessionIn(project_id="p1", owner_type="idea",
                                       owner_id=child["id"], name="子线"))["session"]
    with pytest.raises(HTTPException, match="冻结"):
        _system_parts(dict(session), MsgIn())   # LLM 调用前拦截,零 token


def test_book_context_feeds_open_ideas_only(tmp_db):
    idea_open = _mk_idea(title="开放中的点子")
    idea_drop = _mk_idea(title="已放弃点子")
    patch_idea(idea_drop["id"], PatchIn(status="dropped"))
    idea_adopt = _mk_idea(title="已采纳点子")
    patch_idea(idea_adopt["id"], PatchIn(status="adopted"))
    ctx = build_book_context("p1")
    assert "待议构思(开放讨论中)" in ctx
    assert "开放中的点子" in ctx
    assert "已放弃点子" not in ctx       # 判据:放弃(冻结)不再喂 AI
    assert "已采纳点子" not in ctx       # 已采纳收敛,不再占书级上下文


def test_book_context_unchanged_without_ideas(tmp_db):
    """判据:默认零配置行为不变——没建过构思,书级上下文无新段。"""
    ctx = build_book_context("p1")
    assert "待议构思" not in ctx
    assert "本书信息" in ctx     # 原有段落原样


def test_chain_helper(tmp_db):
    root = _mk_idea(title="根")
    child = _mk_idea(title="子", parent_idea_id=root["id"])
    chain = chain_for_context(child["id"])
    assert [i["title"] for i in chain] == ["根", "子"]
    assert latest_parent_digest(root["id"]) == ""   # 无历史线=空摘要,不炸
