"""精修期第二批回归(C1 层级/场景五字段/C3 节点上下文/C4 分支,执行书 2026-08-31)。"""
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


def _seed_book() -> str:
    """总纲 cat1 → 卷 vol1(→ 近纲 arc1)→ 章 ch1;返回各 id。"""
    from app.routers.outline import NodeIn, create_node
    from app.db import tx
    with tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at)"
            " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
    cat = create_node("p1", NodeIn(kind="category", parent_id=None, title="总纲一"))["id"]
    vol = create_node("p1", NodeIn(kind="volume", parent_id=cat, title="卷一"))["id"]
    ch = create_node("p1", NodeIn(kind="chapter", parent_id=vol, title="第一章"))["id"]  # 章直挂卷
    create_node("p1", NodeIn(kind="arc", parent_id=vol, title="近纲一"))
    return ch


# ── C1 层级:近纲可选 / 场景挂章 ──

def test_chapter_directly_under_volume(tmp_db):
    """章可直接挂卷(近纲可选,拍板判据②);章挂总纲拒绝。"""
    from app.routers.outline import NodeIn, create_node
    ch = _seed_book()
    assert ch  # _seed_book 里第一章已直挂卷,能建即通过
    from app.db import tx
    with tx() as conn:
        cat = conn.execute("SELECT id FROM outline_nodes WHERE kind='category'").fetchone()["id"]
    with pytest.raises(HTTPException):
        create_node("p1", NodeIn(kind="chapter", parent_id=cat, title="挂总纲的章"))


def test_scene_only_under_chapter(tmp_db):
    """场景(beat)挂章下;挂卷/近纲拒绝(拍板 C1)。"""
    from app.routers.outline import NodeIn, create_node
    ch = _seed_book()
    scene = create_node("p1", NodeIn(kind="scene", parent_id=ch, title="场景一"))["id"]
    assert scene
    from app.db import tx
    with tx() as conn:
        vol = conn.execute("SELECT id FROM outline_nodes WHERE kind='volume'").fetchone()["id"]
    with pytest.raises(HTTPException):
        create_node("p1", NodeIn(kind="scene", parent_id=vol, title="挂卷的场景"))


def test_scene_not_in_status_machine(tmp_db):
    """场景不进章节状态机(改状态被拒);章不受影响。"""
    from app.routers.outline import NodeIn, StatusIn, change_status, create_node
    ch = _seed_book()
    scene = create_node("p1", NodeIn(kind="scene", parent_id=ch, title="场景一"))["id"]
    with pytest.raises(HTTPException):
        change_status(scene, StatusIn(to_status="draft"))


# ── C1/C2 场景五字段 + 节点详情 ──

def test_scene_fields_roundtrip(tmp_db):
    """五字段编辑落库,detail 返回解析后的对象;章节点拒绝五字段。"""
    from app.routers.outline import (
        NodeIn, SceneFieldsIn, create_node, node_detail, put_scene_fields,
    )
    ch = _seed_book()
    scene = create_node("p1", NodeIn(kind="scene", parent_id=ch, title="场景一"))["id"]
    put_scene_fields(scene, SceneFieldsIn(
        goal="拿到残纸线索", conflict="书贩子不肯开口",
        hook="旧书贩子留下一句暗语", characters="陈昼、旧书贩子", target_words="800"))
    detail = node_detail(scene)["node"]
    assert detail["scene_fields"]["goal"] == "拿到残纸线索"
    assert detail["scene_fields"]["target_words"] == "800"
    with pytest.raises(HTTPException):
        put_scene_fields(ch, SceneFieldsIn(goal="章不该有五字段"))


def test_node_detail_structure(tmp_db):
    """detail:节点全字段 + 子节点 + 状态日志 + 字段历史(空列表兜底)。"""
    from app.routers.outline import NodeIn, create_node, node_detail
    ch = _seed_book()
    create_node("p1", NodeIn(kind="scene", parent_id=ch, title="章下场景"))
    d = node_detail(ch)["node"]
    assert d["title"] == "第一章"
    assert any(c["kind"] == "scene" for c in d["children"])
    assert d["status_log"] == [] and d["field_history"] == []
    assert d["scene_fields"] == {}


def test_update_node_summary_note(tmp_db):
    """summary/note 人可编辑落库(C2 抽屉);全空 patch 拒绝。"""
    from app.routers.outline import NodePatch, update_node
    ch = _seed_book()
    update_node(ch, NodePatch(summary="本章目标:建立倒计时规则", note="备用结尾:镜裂"))
    from app.routers.outline import node_detail
    d = node_detail(ch)["node"]
    assert d["summary"] == "本章目标:建立倒计时规则"
    assert d["note"] == "备用结尾:镜裂"
    with pytest.raises(HTTPException):
        update_node(ch, NodePatch())


# ── C3 节点上下文装配 ──

def test_build_node_context_trims_l1(tmp_db):
    """节点上下文含祖先链/本节点/L1 常驻;超限裁 L1 保留大纲位置与本节点。"""
    from app.db import tx
    from app.assembly import build_node_context
    from app.routers.outline import NodeIn, NodePatch, create_node, update_node
    ch = _seed_book()
    update_node(ch, NodePatch(summary="倒计时规则建立章"))
    with tx() as conn:
        long_text = "主角设定" * 200
        conn.execute(
            "INSERT INTO l1_entries(id, project_id, category, name, content, presence,"
            " created_at, updated_at)"
            " VALUES('e1','p1','character','陈昼',?,'always','2026-09-01','2026-09-01')",
            (long_text,))
    ctx = build_node_context("p1", ch, limit=6000)
    assert "大纲位置(祖先链)" in ctx and "总纲一" in ctx
    assert "本节点" in ctx and "倒计时规则建立章" in ctx
    assert "陈昼" in ctx
    # 极小上限:L1 被裁,祖先链与本节点保留
    small = build_node_context("p1", ch, limit=200)
    assert "大纲位置(祖先链)" in small and "本节点" in small
    assert "陈昼" not in small


# ── C4 分支全流程 ──

def _mk_branch(ch):
    from app.routers.branches import BranchIn, create_branch
    return create_branch(BranchIn(node_id=ch, name="试一把改名"))["branch"]


def test_branch_lifecycle(tmp_db):
    """建分支(快照=主干)→ 改草稿(主干不变)→ 转正(主干更新+原值入史+分支结案)。"""
    from app.db import tx
    from app.routers.branches import (
        BranchPayloadIn, BranchIn, create_branch, promote_branch, put_branch_payload,
    )
    ch = _seed_book()
    br = create_branch(BranchIn(node_id=ch, name="改名分支"))["branch"]
    assert br["branch_payload"]["title"] == "第一章"
    assert br["status"] == "active"
    # 改草稿
    put_branch_payload(br["id"], BranchPayloadIn(payload={
        "title": "零二一七", "summary": "草稿摘要"}))
    with tx() as conn:
        row = conn.execute(
            "SELECT branch_payload FROM conversation_sessions WHERE id=?", (br["id"],)).fetchone()
        node = conn.execute("SELECT title FROM outline_nodes WHERE id=?", (ch,)).fetchone()
    assert json.loads(row["branch_payload"])["title"] == "零二一七"
    assert node["title"] == "第一章"          # 主干纹丝不动
    # 转正
    r = promote_branch(br["id"])
    fields = {a["field"]: a for a in r["applied"]}
    assert fields["title"]["before"] == "第一章"
    assert fields["title"]["after"] == "零二一七"
    with tx() as conn:
        node = conn.execute("SELECT title, summary FROM outline_nodes WHERE id=?", (ch,)).fetchone()
        hist = conn.execute(
            "SELECT field, before, after, source FROM outline_field_history"
            " WHERE node_id=?", (ch,)).fetchall()
        br_row = conn.execute(
            "SELECT status FROM conversation_sessions WHERE id=?", (br["id"],)).fetchone()
    assert node["title"] == "零二一七" and node["summary"] == "草稿摘要"
    assert any(h["before"] == "第一章" and h["source"] == "branch_promote" for h in hist)
    assert br_row["status"] == "archived"
    # 已结案:再转正/再改草稿都被拒
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        promote_branch(br["id"])
    with pytest.raises(HTTPException):
        put_branch_payload(br["id"], BranchPayloadIn(payload={"title": "再改"}))


def test_branch_title_empty_and_scope(tmp_db):
    """草稿标题空值拒绝;只有章/场景可开分支。"""
    from app.routers.branches import (
        BranchIn, BranchPayloadIn, create_branch, put_branch_payload,
    )
    ch = _seed_book()
    with pytest.raises(HTTPException):
        create_branch(BranchIn(node_id=ch, name="  "))
    vol = None
    from app.db import tx
    with tx() as conn:
        vol = conn.execute("SELECT id FROM outline_nodes WHERE kind='volume'").fetchone()["id"]
    with pytest.raises(HTTPException):
        create_branch(BranchIn(node_id=vol, name="卷不能开分支"))
    br = create_branch(BranchIn(node_id=ch, name="分支"))["branch"]
    with pytest.raises(HTTPException):
        put_branch_payload(br["id"], BranchPayloadIn(payload={"title": "  "}))


def test_delete_node_cleans_sessions(tmp_db):
    """删节点级联清挂在节点上的会话(审稿/节点对话/分支)。"""
    from app.db import tx
    from app.routers.branches import BranchIn, create_branch
    from app.routers.outline import delete_node
    ch = _seed_book()
    create_branch(BranchIn(node_id=ch, name="分支"))
    with tx() as conn:
        n_before = conn.execute("SELECT COUNT(*) c FROM conversation_sessions").fetchone()["c"]
    delete_node(ch)
    with tx() as conn:
        n_after = conn.execute("SELECT COUNT(*) c FROM conversation_sessions").fetchone()["c"]
        assert conn.execute("SELECT COUNT(*) c FROM outline_nodes WHERE id=?", (ch,)).fetchone()["c"] == 0
    assert n_before >= 1 and n_after == 0


def test_delete_node_cleans_tasks_changesets_messages(tmp_db):
    """S8 回归(2026-09-01):删章后 gen_tasks/changesets+patches/review_messages 零孤儿。

    review_messages 经 conversation_sessions 挂节点,会话删除在先,
    必须按 session_id 前置查出再删,不能按已不存在的 owner 直查。
    """
    from app.db import tx
    from app.routers.outline import delete_node
    ch = _seed_book()
    with tx() as conn:
        conn.execute(
            "INSERT INTO gen_tasks(id, project_id, node_id, created_at, updated_at)"
            " VALUES('t1','p1',?, 't','t')", (ch,))
        conn.execute(
            "INSERT INTO changesets(id, project_id, node_id, created_at, updated_at)"
            " VALUES('cs1','p1',?, 't','t')", (ch,))
        conn.execute(
            "INSERT INTO changeset_patches(id, changeset_id, target_id, after)"
            " VALUES('pt1','cs1',?, '新正文')", (ch,))
        conn.execute(
            "INSERT INTO conversation_sessions(id, project_id, owner_type, owner_id,"
            " name, created_at) VALUES('s1','p1','outline_node',?,'节点对话','t')", (ch,))
        conn.execute(
            "INSERT INTO review_messages(id, project_id, node_id, session_id, role,"
            " content, created_at) VALUES('m1','p1',?, 's1','user','你好','t')", (ch,))
    delete_node(ch)
    with tx() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM gen_tasks WHERE node_id=?", (ch,)).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM changesets WHERE node_id=?", (ch,)).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM changeset_patches WHERE id='pt1'").fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM review_messages WHERE session_id='s1'").fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM conversation_sessions WHERE id='s1'").fetchone()["c"] == 0


# ── settings 档位表合并(C3 实测发现的浅合并坑)──

def test_thinking_by_action_keywise_merge(tmp_db):
    """库中旧档位表(浅合并会整键覆盖)不得吃掉 DEFAULTS 新增 action 的默认档。

    实测:存量 settings.thinking 不含 outline_chat 键,浅合并下新 action 落到
    default=high,违背"新对话类 action 一律先 low"的拍板——get_settings 必须对
    by_action 做键级合并(DEFAULTS 打底,库值优先)。
    """
    import json as _json
    from app.db import tx
    from app.ledger.usage import resolve_thinking_level
    with tx() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES('thinking', ?, 't')",
            (_json.dumps({"enabled": True, "model_match": "glm", "default": "high",
                          "by_action": {"chapter_draft": "max"}}),))
    assert resolve_thinking_level("outline_chat", "glm-5.3-flash") == "low"
    assert resolve_thinking_level("chapter_draft", "glm-5.3-flash") == "max"   # 库值优先
