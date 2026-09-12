"""WPS 式大纲回归(任务词 2026-09-09):topic 轻节点/节点 body/装配注入开关/AI 闸门。

红线钉:类型不丢(topic 无状态机不计章数,章仍只挂卷/近纲)/老书零破坏
(body 默认空、注入默认关,行为与基线分毫不差)/AI 永不直写(落库唯一路径=
人批准闸门 adopt_subtopic_tree)。
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402
from app.assembly import build_assembly  # noqa: E402
from app.routers.adopt import (  # noqa: E402
    AdoptIn, adopt_subtopic_tree, adopt_suggestion, sanitize_subtopic_tree,
)
from app.routers.outline import (  # noqa: E402
    NodeIn, NodePatch, StatusIn, change_status, create_node, delete_node,
    node_detail, update_node,
)
from app.routers.outline_ai import SubtopicAdoptIn, adopt_subtopics  # noqa: E402


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
    yield dbmod
    dbmod._conn = None


def _mk(kind: str, title: str, parent: str | None = None, pid: str = "p1") -> str:
    if kind == "volume" and parent is None:
        with tx() as conn:
            root = conn.execute(
                "SELECT id FROM outline_nodes WHERE project_id=? AND kind='category'",
                (pid,)).fetchone()
        parent = root[0] if root else _mk("category", "总纲", pid=pid)
    return create_node(pid, NodeIn(kind=kind, parent_id=parent, title=title))["id"]


# ── 迁移 v22 ──

def test_migration_v22_body_column(tmp_db):
    """body 列在、NOT NULL DEFAULT ''(老行零回填成本)。"""
    with tx() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(outline_nodes)").fetchall()}
    assert version >= 22
    assert "body" in cols
    assert cols["body"][3] == 1      # notnull
    assert cols["body"][4] == "''"   # dflt_value=SQL 文本(pragma 原样返回)


# ── topic 节点:挂载规则/无限嵌套 ──

def test_topic_nested_chain(tmp_db):
    """卷→子题→子题→子题 3 层链 + 章下挂子题(任务词判据)。"""
    vol = _mk("volume", "第一卷")
    t1 = _mk("topic", "装备系统", parent=vol)
    t2 = _mk("topic", "苏晴的钥匙", parent=t1)
    ch = _mk("chapter", "第1章 码头", parent=vol)
    t3 = _mk("topic", "码头相遇", parent=ch)
    with tx() as conn:
        kinds = {r["id"]: r["kind"] for r in conn.execute(
            "SELECT id, kind FROM outline_nodes").fetchall()}
    assert kinds[t1] == kinds[t2] == kinds[t3] == "topic"


def test_topic_parent_rules_type_not_lost(tmp_db):
    """类型不丢红线:章仍只挂卷/近纲;topic 不能挂总纲/场景;topic 可挂 topic。"""
    cat = _mk("category", "总纲")
    vol = _mk("volume", "第一卷")
    ch = _mk("chapter", "第1章", parent=vol)
    sc = _mk("scene", "开场", parent=ch)
    t = _mk("topic", "子题", parent=ch)
    with pytest.raises(HTTPException, match="只能挂在"):
        _mk("chapter", "第2章", parent=t)          # 章不能挂子题下(状态机类型不丢)
    with pytest.raises(HTTPException, match="只能挂在"):
        _mk("topic", "子题", parent=cat)           # 总纲下不挂子题
    with pytest.raises(HTTPException, match="只能挂在"):
        _mk("topic", "子题", parent=sc)            # 场景下不挂子题
    _mk("topic", "孙题", parent=t)                 # topic 挂 topic 放行


def test_topic_no_state_machine_and_no_count(tmp_db):
    """topic 无状态机(迁移拒绝);列表/详情不出状态标签;不计章数。"""
    vol = _mk("volume", "第一卷")
    t = _mk("topic", "子题", parent=vol)
    with pytest.raises(HTTPException, match="只有章节点有状态机"):
        change_status(t, StatusIn(to_status="draft"))
    detail = node_detail(t)["node"]
    assert detail["status_label"] is None
    assert detail["allowed_transitions"] == []
    # 卷下 19 个 topic:章密度失衡不触发(topic 不计入章数)
    for i in range(19):
        _mk("topic", f"子题{i}", parent=vol)
    from app.routers.diagnostics import _algorithm_check_rows
    checks = {c["key"]: c["count"] for c in _algorithm_check_rows("p1")}
    assert checks["dense_parent"] == 0
    assert checks["orphan_chapter"] == 0


def test_topic_delete_cascade(tmp_db):
    vol = _mk("volume", "第一卷")
    t1 = _mk("topic", "上层", parent=vol)
    t2 = _mk("topic", "中层", parent=t1)
    t3 = _mk("topic", "下层", parent=t2)
    r = delete_node(t2)
    assert r["deleted"] == 2   # 中层+下层
    with tx() as conn:
        left = {r["id"] for r in conn.execute("SELECT id FROM outline_nodes").fetchall()}
    assert t2 not in left and t3 not in left and t1 in left


# ── body 读写 ──

def test_body_roundtrip_and_limit(tmp_db):
    vol = _mk("volume", "第一卷")
    t = _mk("topic", "装备系统", parent=vol)
    update_node(t, NodePatch(body="成段的装备设定正文。"))
    assert node_detail(t)["node"]["body"] == "成段的装备设定正文。"
    update_node(t, NodePatch(body=""))   # 清空允许
    assert node_detail(t)["node"]["body"] == ""
    with pytest.raises(HTTPException, match="超长"):
        update_node(t, NodePatch(body="x" * 20001))
    update_node(t, NodePatch(body="y" * 20000))   # 上限内放行


# ── 装配注入开关(默认关=老书零破坏)──

def _mk_book_with_body(tmp_db):
    vol = _mk("volume", "第一卷")
    update_node(vol, NodePatch(body="卷正文" + "甲" * 400))
    ch = _mk("chapter", "第1章 码头", parent=vol)
    t = _mk("topic", "同级子题", parent=ch)
    update_node(t, NodePatch(body="子题正文" + "乙" * 400))
    return vol, ch, t


def test_assembly_body_inject_default_off(tmp_db):
    """默认关:装配体无 body 段(老书行为与基线分毫不差)。"""
    _mk_book_with_body(tmp_db)
    with tx() as conn:
        ch = conn.execute("SELECT id FROM outline_nodes WHERE kind='chapter'").fetchone()[0]
    result = build_assembly("p1", ch, log=False)
    assert not any(s["source"] == "outline:body" for s in result["sections"])


def test_assembly_body_inject_on(tmp_db):
    """开启:祖先链(卷)、同级 topic 与章直属子题的 body 摘要进 on_demand 段,各截 300 字。"""
    import app.settings_store as st
    vol, ch, _ = _mk_book_with_body(tmp_db)
    t_sib = _mk("topic", "同级子题", parent=vol)     # 与章同父(任务词"同级")
    update_node(t_sib, NodePatch(body="子题正文" + "乙" * 400))
    st.update_settings("assembly", {"body_inject": True})
    result = build_assembly("p1", ch, log=False)
    body_secs = [s for s in result["sections"] if s["source"] == "outline:body"]
    assert len(body_secs) == 3   # 卷 + 同级子题 + 章直属子题(邻近原则)
    assert all(s["kind"] == "on_demand" for s in body_secs)
    for s in body_secs:
        assert len(s["content"]) == 300 + len("…(截断)")
    # 超限先裁:on_demand body 段先于常驻被裁(裁到 ≤limit 即停=既有契约,
    # 残余超限由 over_limit 记录在案)
    st.update_settings("assembly", {"token_limit": 400})
    tight = build_assembly("p1", ch, log=False)
    cut = [s for s in tight["sections"] if s["source"] == "outline:body"]
    assert any(not s["included"] for s in cut)
    assert all(s.get("trimmed_by_limit") for s in cut if not s["included"])
    st.update_settings("assembly", {"token_limit": 6000})


def test_node_context_carries_body(tmp_db):
    """节点对话上下文带正文(3000 截断);body 空时不出现该行=老书零变化。"""
    from app.assembly import build_node_context
    vol = _mk("volume", "第一卷")
    update_node(vol, NodePatch(body="正" * 3500))
    ctx = build_node_context("p1", vol)
    assert "正文:" in ctx and "…(截断)" in ctx
    ch = _mk("chapter", "第1章", parent=vol)
    assert "正文:" not in build_node_context("p1", ch)


# ── AI 闸门:AI 永不直写,落库唯一路径=人批准 ──

def test_sanitize_subtopic_tree(tmp_db):
    tree = sanitize_subtopic_tree([
        {"title": "  码头相遇  ", "children": [{"title": "", "note": "垃圾"}, {"title": "钥匙"}]},
        "垃圾项", {}, {"title": ""},
    ])
    assert tree == [{"title": "码头相遇", "children": [{"title": "钥匙", "children": []}]}]
    long_tree = sanitize_subtopic_tree([{"title": "x" * 500}])
    assert len(long_tree[0]["title"]) == 120
    with pytest.raises(HTTPException, match="嵌套过深"):
        deep = {"title": "0", "children": []}
        cur = deep
        for i in range(1, 15):
            cur["children"] = [{"title": str(i), "children": []}]
            cur = cur["children"][0]
        sanitize_subtopic_tree([deep])


def test_adopt_subtopic_tree_gate(tmp_db):
    """闸门落地:3 层树落 topic;父类型校验;空树/超量拒绝;留 human_gate 痕。"""
    vol = _mk("volume", "第一卷")
    r = adopt_subtopic_tree(vol, [
        {"title": "装备系统", "children": [
            {"title": "苏晴的钥匙", "children": [{"title": "钥匙的三段变化"}]}]},
        {"title": "码头相遇"},
    ])
    assert r["created"] == 4
    with tx() as conn:
        rows = {r2["title"]: r2 for r2 in conn.execute(
            "SELECT id, kind, title, parent_id, status FROM outline_nodes"
            " WHERE kind='topic'").fetchall()}
        run = conn.execute("SELECT action, agent_type, status FROM agent_runs"
                           " WHERE action='adopt_subtopic_add'").fetchone()
    assert set(rows) == {"装备系统", "苏晴的钥匙", "钥匙的三段变化", "码头相遇"}
    assert rows["钥匙的三段变化"]["parent_id"] == rows["苏晴的钥匙"]["id"]
    assert all(v["status"] == "unwritten" for v in rows.values())
    assert run["agent_type"] == "human_gate" and run["status"] == "succeeded"
    with pytest.raises(HTTPException, match="没有有效的子题"):
        adopt_subtopic_tree(vol, [{"title": ""}])
    with pytest.raises(HTTPException, match="过大"):
        adopt_subtopic_tree(vol, [{"title": f"t{i}"} for i in range(101)])
    cat = _mk("category", "总纲")
    with pytest.raises(HTTPException, match="不能挂在"):
        adopt_subtopic_tree(cat, [{"title": "x"}])
    with pytest.raises(HTTPException, match="不存在"):
        adopt_subtopic_tree("node_missing", [{"title": "x"}])


def test_adopt_endpoint_and_suggestion_path(tmp_db):
    """两条闸门路径同源:outline_ai.adopt_subtopics 与对话建议 subtopic_add。"""
    vol = _mk("volume", "第一卷")
    r = adopt_subtopics(vol, SubtopicAdoptIn(tree=[{"title": "A", "children": [{"title": "B"}]}]))
    assert r["created"] == 2 and r["ok"] is True
    # 对话建议路径:构造 assistant 消息 meta 带 subtopic_add 建议 → adopt_suggestion
    ch = _mk("chapter", "第1章", parent=vol)
    with tx() as conn:
        conn.execute(
            "INSERT INTO review_messages(id, session_id, node_id, role, content, meta,"
            " created_at) VALUES('m1', 's1', ?, 'assistant', '建议拆子题', ?, '2026-09-09')",
            (ch, json.dumps({"suggestions": [{
                "quote": "", "issue": "正文可拆", "suggestion": "拆两层",
                "severity": "minor", "target_type": "subtopic_add",
                "target": {"node_id": ch, "tree": [{"title": "码头相遇"}]},
            }]}, ensure_ascii=False)))
        conn.execute("INSERT INTO conversation_sessions(id, project_id, owner_type,"
                     " owner_id, name, created_at) VALUES('s1', 'p1', 'outline_node',"
                     " ?, '线', '2026-09-09')", (ch,))
    out = adopt_suggestion(AdoptIn(session_id="s1", message_id="m1", index=0))
    assert out["created"] == 1
    with tx() as conn:
        n = conn.execute("SELECT COUNT(*) FROM outline_nodes WHERE kind='topic'"
                         " AND parent_id=?", (ch,)).fetchone()[0]
    assert n == 1
    with pytest.raises(HTTPException, match="已采纳过"):
        adopt_suggestion(AdoptIn(session_id="s1", message_id="m1", index=0))


def test_new_touches_thinking_defaults(tmp_db):
    """触点/思考档位登记生效:新 action 有默认档(库中旧档位表不吃掉新键)。"""
    from app.settings_store import TOUCHES, get_settings, get_touch_overrides
    assert TOUCHES["outline_subtopic_split"]["max_tokens"] == 8000
    assert TOUCHES["outline_body_suggest"]["max_tokens"] == 4000
    by_action = get_settings()["thinking"]["by_action"]
    assert by_action["outline_subtopic_split"] == "low"
    assert by_action["outline_body_suggest"] == "low"
    assert get_touch_overrides("outline_subtopic_split") == {}   # 零配置零破坏
