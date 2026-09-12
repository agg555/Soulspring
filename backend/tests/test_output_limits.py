"""输出上下限三层体系+参考提示词库回归(2026-09-09 拍板)。

上限生效链=书×触点>书默认>触点 touches>全局默认>出厂登记;下限=告警线
(回包低于下限标 limit_warning,不拦截);参考提示词=库+三层绑定(命中层不叠加,
运行时手选优先)+注入段。
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.settings_store as st  # noqa: E402
from app.settings_store import (  # noqa: E402
    get_settings, ref_prompt_section, resolve_ref_prompt_ids,
)


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


from app.ledger.usage import _resolve_max_tokens, _resolve_min_tokens  # noqa: E402


def test_max_tokens_precedence_chain(tmp_db):
    """上限生效链逐层验证:书×触点 > 书默认 > touches > 全局默认 > 登记。"""
    action = "outline_chat"
    reg = get_settings().get("touches") or {}
    _ = reg
    from app.settings_store import TOUCHES
    # 零配置=登记值
    assert _resolve_max_tokens(action, touch_max=None, project_id="p1") \
        == TOUCHES[action]["max_tokens"]
    # 全局默认
    st.update_settings("output_limits", {"default": {"min_tokens": 100, "max_tokens": 5000}})
    assert _resolve_max_tokens(action, touch_max=None, project_id="p1") == 5000
    # 触点 touches 压过全局默认
    assert _resolve_max_tokens(action, touch_max=9000, project_id="p1") == 9000
    # 书默认压过 touches
    st.update_settings("output_limits", {"books": {"p1": {
        "default": {"min_tokens": 200, "max_tokens": 12000}}}})
    assert _resolve_max_tokens(action, touch_max=9000, project_id="p1") == 12000
    # 书×触点最高
    st.update_settings("output_limits", {"books": {"p1": {
        "default": {"min_tokens": 200, "max_tokens": 12000},
        "actions": {action: {"min_tokens": 300, "max_tokens": 15000}}}}})
    assert _resolve_max_tokens(action, touch_max=9000, project_id="p1") == 15000
    # 其他书不受影响
    assert _resolve_max_tokens(action, touch_max=9000, project_id="p2") == 9000


def test_min_tokens_warning_chain(tmp_db):
    st.update_settings("output_limits", {"default": {"min_tokens": 100}})
    assert _resolve_min_tokens("chapter_draft", "p1") == 100
    st.update_settings("output_limits", {"books": {"p1": {
        "default": {"min_tokens": 200}}}})
    assert _resolve_min_tokens("chapter_draft", "p1") == 200
    st.update_settings("output_limits", {"books": {"p1": {
        "default": {"min_tokens": 200},
        "actions": {"chapter_draft": {"min_tokens": 300}}}}})
    assert _resolve_min_tokens("chapter_draft", "p1") == 300
    assert _resolve_min_tokens("chapter_draft", "p2") == 100   # 其他书走全局


def test_zero_and_negative_treated_as_unset(tmp_db):
    """0/负数=未配置(防御);上限链回落登记值。"""
    st.update_settings("output_limits", {"default": {"min_tokens": 0, "max_tokens": -5}})
    assert _resolve_min_tokens("chapter_draft", "p1") is None
    from app.settings_store import TOUCHES
    assert _resolve_max_tokens("chapter_draft", touch_max=None, project_id="p1") \
        == TOUCHES["chapter_draft"]["max_tokens"]


def test_output_limits_put_and_shape(tmp_db):
    from app.routers.settings_api import BookLimits, LimitPair, OutputLimitsIn, put_output_limits
    r = put_output_limits(OutputLimitsIn(
        default=LimitPair(min_tokens=100, max_tokens=8000),
        books={"p1": BookLimits(
            default=LimitPair(min_tokens=200),
            actions={"outline_chat": LimitPair(max_tokens=15000)})}))
    ol = r["output_limits"]
    assert ol["default"] == {"min_tokens": 100, "max_tokens": 8000}
    assert ol["books"]["p1"]["actions"]["outline_chat"] == {"min_tokens": None, "max_tokens": 15000}


# ── 参考提示词库与绑定 ──

def _seed_prompts():
    from app.routers.settings_api import RefPromptItem, ReferencePromptsIn, put_reference_prompts
    return put_reference_prompts(ReferencePromptsIn(
        items=[RefPromptItem(id="a", name="武侠腔", text="用武侠腔行文,短句为主。"),
               RefPromptItem(id="b", name="多环境描写", text="每场景至少一段环境描写。"),
               RefPromptItem(id="c", name="少用成语", text="避免堆砌成语。")],
        global_bind=["a"],
        actions={"chapter_draft": ["b"]},
        books={"p1": ["c"]}))


def test_ref_prompt_binding_precedence(tmp_db):
    """命中层不叠加:手选 > 书 > 触点 > 全局。"""
    _seed_prompts()
    assert resolve_ref_prompt_ids("chapter_draft", "p1", ["a", "b"]) == ["a", "b"]  # 手选
    assert resolve_ref_prompt_ids("chapter_draft", "p1") == ["c"]                   # 书
    assert resolve_ref_prompt_ids("chapter_draft", "p2") == ["b"]                   # 触点
    assert resolve_ref_prompt_ids("outline_chat", "p2") == ["a"]                    # 全局


def test_ref_prompt_section_injection(tmp_db):
    _seed_prompts()
    sec = ref_prompt_section("chapter_draft", "p1")
    assert "参考提示词" in sec and "避免堆砌成语" in sec and "武侠腔" not in sec
    # 空手选=明确不用,不注入
    assert ref_prompt_section("chapter_draft", "p1", []) == ""
    assert ref_prompt_section("chapter_draft", "p2", None) != ""


def test_reference_prompts_put_validation(tmp_db):
    from app.routers.settings_api import (
        RefPromptItem, ReferencePromptsIn, put_reference_prompts)
    put_reference_prompts(ReferencePromptsIn(items=[
        RefPromptItem(id="a", name="A", text="内容")], global_bind=["a"]))
    with pytest.raises(HTTPException, match="名称不能为空"):
        put_reference_prompts(ReferencePromptsIn(items=[RefPromptItem(id="x", name=" ", text="t")]))
    with pytest.raises(HTTPException, match="内容为空"):
        put_reference_prompts(ReferencePromptsIn(items=[RefPromptItem(id="x", name="n", text="  ")]))
    with pytest.raises(HTTPException, match="重复"):
        put_reference_prompts(ReferencePromptsIn(items=[
            RefPromptItem(id="x", name="n1", text="t"),
            RefPromptItem(id="x", name="n2", text="t")]))
    with pytest.raises(HTTPException, match="不存在"):
        put_reference_prompts(ReferencePromptsIn(items=[RefPromptItem(id="a", name="A", text="t")],
                                                 global_bind=["ghost"]))


def test_generate_in_accepts_ref_ids(tmp_db):
    """草稿/自修入参通道(结构冒烟):ref_prompt_ids 进 GenerateIn。"""
    from app.routers.workbench import GenerateIn
    body = GenerateIn(skill=None, ref_prompt_ids=["a", "b"])
    assert body.ref_prompt_ids == ["a", "b"]
    assert GenerateIn().ref_prompt_ids is None
