"""批次六甲乙回归:触点登记/解析/零破坏/追加与覆盖/API CRUD;乙件回执透传。"""
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


from app.settings_store import (  # noqa: E402
    TOUCHES,
    get_settings,
    get_touch_overrides,
    touch_prompt_append,
)
from app.routers.conversations import REPLY_PROTOCOL, _system_parts  # noqa: E402
from app.routers.settings_api import TouchesIn, put_touches  # noqa: E402


def test_registry_complete_and_typed():
    """判据①前置:登记 19 键、字段齐全(动作级口径;章节卡预填 +1)。"""
    assert len(TOUCHES) == 19
    for k, v in TOUCHES.items():
        assert {"label", "kind", "hosts", "max_tokens"} <= set(v), k
        assert v["kind"] in ("dialog", "oneshot"), k
    assert sum(1 for v in TOUCHES.values() if v["kind"] == "dialog") == 5


def test_default_zero_config_no_break(tmp_db):
    """判据①:零配置=无覆盖,现行为分毫不变。"""
    assert get_settings()["touches"] == {}
    assert get_touch_overrides("chapter_draft") == {}
    assert touch_prompt_append("book_chat") == ""


def test_overrides_parse_and_isolation(tmp_db):
    """判据②:append 只影响所配触点;model/max_tokens 类型清洗。"""
    import app.settings_store as st
    st.update_settings("touches", {"chapter_plan": {
        "prompt_append": "始终用武侠腔。", "model": "glm-4.7-flash", "max_tokens": 4096}})
    ov = get_touch_overrides("chapter_plan")
    assert ov["prompt_append"] == "始终用武侠腔。" and ov["model"] == "glm-4.7-flash"
    assert ov["max_tokens"] == 4096
    # 其他触点不受影响
    assert get_touch_overrides("chapter_draft") == {}
    assert touch_prompt_append("chapter_draft") == ""
    # 非法项清洗:bool 冒充 int/短字符串/未知键丢弃
    st.update_settings("touches", {"chapter_draft": {"max_tokens": True, "model": "  "},
                                   "book_chat": "垃圾"})
    assert get_touch_overrides("chapter_draft") == {}
    assert get_touch_overrides("book_chat") == {}


def test_prompt_append_position_before_protocol(tmp_db):
    """判据②补:对话组装里追加在 REPLY_PROTOCOL 之前(协议恒在末尾)。"""
    import app.settings_store as st
    st.update_settings("touches", {"chat_test": {"prompt_append": "【触点追加】"}})
    session = {"owner_type": "chat_test", "owner_id": "", "project_id": "", "id": "x",
               "digest": ""}
    body = type("B", (), {"attachments": [], "ref_prompt_ids": None, "preset_text": None, "preset": None})()
    parts = _system_parts(session, body)
    assert "【触点追加】" in parts
    assert parts.index("【触点追加】") < len(parts) - 1   # 协议是最后一段
    assert REPLY_PROTOCOL in parts[-1]


def test_put_touches_crud_and_validation(tmp_db):
    """判据⑤:增删改查+校验 422(未知键/非法上限)。"""
    from fastapi import HTTPException
    put_touches(TouchesIn(touches={"llm_test": {"max_tokens": 256, "model": "glm-4.7-flash"}}))
    saved = get_settings()["touches"]
    assert saved["llm_test"] == {"max_tokens": 256, "model": "glm-4.7-flash"}
    # 改:保留 model 改上限
    put_touches(TouchesIn(touches={"llm_test": {"max_tokens": 1024}}))
    assert get_settings()["touches"]["llm_test"] == {"max_tokens": 1024}
    # 删:全量替换语义(空 map 清空,不被合并还魂)
    put_touches(TouchesIn(touches={}))
    assert get_settings()["touches"] == {}
    # 校验:未知键 / 非法上限
    with pytest.raises(HTTPException) as e:
        put_touches(TouchesIn(touches={"noSuchTouch": {}}))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        put_touches(TouchesIn(touches={"llm_test": {"max_tokens": 10}}))
    assert e.value.status_code == 422


def test_put_touches_rejects_cross_provider_model(tmp_db):
    """甲件红队②:模型须属当前 provider(实测 DeepSeek 网关拒 glm 名,必 400)。"""
    import app.settings_store as st
    from fastapi import HTTPException
    st.update_settings("llm", {"base_url": "https://api.deepseek.com",
                               "model": "deepseek-v4-flash"})
    with pytest.raises(HTTPException) as e:
        put_touches(TouchesIn(touches={"chaishu_organize": {"model": "glm-4.7-flash"}}))
    assert e.value.status_code == 422 and "不属于当前服务商" in e.value.detail
    # 同厂放行
    put_touches(TouchesIn(touches={"chaishu_organize": {"model": "deepseek-v4-flash"}}))
    assert get_settings()["touches"]["chaishu_organize"]["model"] == "deepseek-v4-flash"
