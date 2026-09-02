"""工作台生成体验回归(2026-08-31 需求稿):豁免键延续 / 技能三档优先级 / MCP 校验。"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.changeset_ops import _carry_dismissals, _dismiss_key  # noqa: E402
from app.settings_store import DEFAULTS, resolve_skill  # noqa: E402


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


# ── S7 回归(审计 2026-09-01):_llm_review 失败必须留痕,不许静默 None ──

def test_llm_review_failure_leaves_trace(tmp_db, monkeypatch):
    """评审管道失败时返回 (review_error, 0.0),不再静默吞掉;成本位为 0。"""
    import app.routers.generation as gen

    def _boom(*args, **kwargs):
        raise RuntimeError("未配 API key")

    monkeypatch.setattr(gen, "chat_completion", _boom)
    node = {"id": "n_nonexist", "title": "第一章"}
    r, cost = gen._llm_review("p1", node, "草稿正文", {})
    assert isinstance(r, dict) and r.get("review_error") and cost == 0.0


# ── 豁免键热修回归:人改后 evidence 变化不得丢豁免(2026-08-31 实测 bug)──

def _char_issue(evidence: str) -> dict:
    return {
        "code": "character_status", "status": "failed", "dimension": "角色状态一致性",
        "message": "角色「陈夜」状态为 missing，但疑似有主动行为",
        "suggestion": "确认「陈夜」是否真的在行动，或修改其状态",
        "auto_fixable": False, "evidence": evidence,
    }


def test_dismiss_key_ignores_evidence_drift():
    """同一问题在正文增删前后 evidence 上下文窗口不同,但豁免键必须相同。"""
    before = _char_issue("……头潮还有不到一个钟头开市，鲸背区那边，阿灰会等他。")
    after = _char_issue("……头潮还有不到一个钟头开市。新追加的结尾句让 ±100 字窗口内容变了。")
    assert before["evidence"] != after["evidence"]
    assert _dismiss_key(before) == _dismiss_key(after)


def test_carry_dismissals_survives_human_edit():
    """人改保存路径:老变更集里的已豁免问题,重审计(新 evidence)后仍带豁免与备注。"""
    old_validations = [
        {**_char_issue("旧证据窗口 A"), "dismissed": True,
         "dismiss_note": "误报:抒情独白非实际出场"},
        {"code": "humanity", "status": "warning", "dimension": "句式同构",
         "message": "连续三句具有相同起句或近似长度与停顿结构,可能形成机械排比",
         "evidence": "旧引用句"},
    ]
    new_validations = [
        _char_issue("人改后的新证据窗口 B(完全不同)"),
        {"code": "humanity", "status": "warning", "dimension": "句式同构",
         "message": "连续三句具有相同起句或近似长度与停顿结构,可能形成机械排比",
         "evidence": "人改后的新引用句"},
    ]
    _carry_dismissals(new_validations, old_validations)
    assert new_validations[0]["dismissed"] is True
    assert new_validations[0]["dismiss_note"] == "误报:抒情独白非实际出场"
    # 未豁免过的 warning 不受影响
    assert "dismissed" not in new_validations[1]


def test_carry_dismissals_does_not_overreach():
    """消息模板不同的问题(如换了个角色名)不继承豁免。"""
    old_validations = [{**_char_issue("窗口"), "dismissed": True, "dismiss_note": "误报"}]
    other_character = {
        "code": "character_status", "status": "failed", "dimension": "角色状态一致性",
        "message": "角色「老葛」状态为 dead，但疑似有主动行为",
        "evidence": "窗口", "auto_fixable": False,
    }
    _carry_dismissals([other_character], old_validations)
    assert "dismissed" not in other_character


# ── 技能三档优先级(需求3):手选 > 单本书 > 全局 > 不启用 ──

def test_skill_priority_overrides(monkeypatch):
    base = {"skills": {"global_default": "", "book_overrides": {}}}

    def fake_settings():
        return {**DEFAULTS, **base}

    import app.settings_store as ss
    monkeypatch.setattr(ss, "get_settings", fake_settings)

    # 全空 → 不启用
    assert resolve_skill("p1") == ""
    # 全局默认生效
    base["skills"]["global_default"] = "违禁检查"
    assert resolve_skill("p1") == "违禁检查"
    # 单本书覆盖压过全局
    base["skills"]["book_overrides"] = {"p1": "说人话"}
    assert resolve_skill("p1") == "说人话"
    assert resolve_skill("p2") == "违禁检查"   # 换书互不干扰
    # 单本书显式不启用("")压过全局
    base["skills"]["book_overrides"] = {"p1": ""}
    assert resolve_skill("p1") == ""
    # 运行时手选压过一切(explicit 非 None 即生效,含空串=明确不启用)
    assert resolve_skill("p1", "story-review") == "story-review"
    assert resolve_skill("p1", "") == ""
