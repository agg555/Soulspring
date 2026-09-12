"""对话正文信道加固+自定义模板回归(2026-09-09 拍板"都做,代码质量优先")。

实锤样本:模型在 JSON 字符串里输出裸换行 → 整条降级原样显示(JSON 壳+字面 \n)。
三级解析(常规/strict=False/正则抽 reply)+协议转义纪律+填空模板 preset_text 通道。
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402


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


# 库里真实样本(2026-09-09 用户截图那条的结构,reply 值内含裸换行)
BARE_NL_JSON = (
    '{"reply": "第一段。\\n\\n第二段开头\n- 列表项一\n- 列表项二\\n结尾。",'
    ' "suggestions": []}'
)
# JSON 壳但 reply 值内有未转义引号(严格与宽松 loads 都救不活)→ 正则抽 reply
BROKEN_JSON = (
    '{"reply": "他说:\\"你好\\"之后\n就走了", "suggestions": '
    '[{"issue": "被截坏的剩余部分'
)
PLAIN_TEXT = "我知道前情提要中包含了多条测试内容,并已按顺序逐一回复。"


def _parse(raw):
    from app.routers.conversations import _parse_reply
    return _parse_reply(raw)


def test_parse_bare_newline_rescued_by_strict_false():
    """一级解析拒裸换行 → strict=False 救活,reply/suggestions 完整。"""
    reply, suggestions, err = _parse(BARE_NL_JSON)
    assert err is False
    assert "第一段" in reply and "列表项一" in reply


def test_parse_broken_json_reply_field_rescue():
    """二级仍失败 → 正则抽 reply 字段(呈现兜底;suggestions 丢弃,parse_error 留真)。"""
    reply, suggestions, err = _parse(BROKEN_JSON)
    assert err is True
    assert "他说" in reply and "你好" in reply
    assert suggestions == []


def test_parse_plain_text_stays_verbatim():
    """模型没按协议说人话:原样降级(现状本就正确,不许"修"它)。"""
    reply, suggestions, err = _parse(PLAIN_TEXT)
    assert err is True and reply == PLAIN_TEXT and suggestions == []


def test_parse_subtopic_add_whitelisted():
    """上轮遗留补:对话协议 subtopic_add 不再被归为 none。"""
    raw = json.dumps({"reply": "建议拆子题", "suggestions": [{
        "quote": "", "issue": "i", "suggestion": "s", "severity": "minor",
        "target_type": "subtopic_add", "target": {"node_id": "n", "tree": []}}]},
        ensure_ascii=False)
    _, suggestions, err = _parse(raw)
    assert err is False and suggestions[0]["target_type"] == "subtopic_add"


def test_reply_protocol_has_escape_and_emoji_rules():
    """协议加固:转义纪律+禁 emoji(2026-09-09 拍板)。"""
    from app.routers.conversations import REPLY_PROTOCOL
    assert "\\n 转义" in REPLY_PROTOCOL and "emoji" in REPLY_PROTOCOL


def test_preset_text_channel_in_system(tmp_db):
    """填空模板指令进 system,位置在 REPLY_PROTOCOL 之前;与内置 preset 可叠加。
    (宿主用 book 线:chat_test/review 不接 preset 通道,是既有划界非缺陷)"""
    from app.routers.conversations import REPLY_PROTOCOL, MessageIn, _system_parts
    session = {"owner_type": "book", "owner_id": "", "project_id": "",
               "id": "x", "digest": ""}
    body = MessageIn(message="m", attachments=[],
                     preset="optimize",
                     preset_text="- 要优化什么?:对话\n- 方向:更口语")
    parts = _system_parts(session, body)
    assert any("作者模板填空指令" in p and "更口语" in p for p in parts)
    assert any("优化模式" in p for p in parts)          # 内置 preset 协议段仍在
    assert REPLY_PROTOCOL in parts[-1]                 # 协议恒在末尾


def test_preset_text_alone_replaces_free_text(tmp_db):
    """仅填空(无内置 preset)也生效;自由文案不再叠加。"""
    from app.routers.conversations import MessageIn, _system_parts
    session = {"owner_type": "book", "owner_id": "", "project_id": "",
               "id": "x", "digest": ""}
    parts = _system_parts(session, MessageIn(message="m", attachments=[],
                                             preset_text="- 围绕:力量体系"))
    assert any("力量体系" in p for p in parts)


# ── 模板库 CRUD 与校验 ──

def test_prompt_templates_crud_and_validation(tmp_db):
    from app.routers.settings_api import PromptTemplatesIn, TemplateIn, put_prompt_templates
    put_prompt_templates(PromptTemplatesIn(items=[TemplateIn(
        id="t1", name="查时间线",
        questions=["围绕什么发散?", "有什么约束?"])]))
    from app.settings_store import get_settings
    items = get_settings()["prompt_templates"]["items"]
    assert len(items) == 1 and items[0]["name"] == "查时间线"
    # 清空=全量替换
    put_prompt_templates(PromptTemplatesIn(items=[]))
    assert get_settings()["prompt_templates"]["items"] == []
    # 校验:空名/空问题/重名 id/超限
    with pytest.raises(HTTPException):
        put_prompt_templates(PromptTemplatesIn(items=[TemplateIn(id="t", name="  ", questions=["q"])]))
    with pytest.raises(HTTPException):
        put_prompt_templates(PromptTemplatesIn(items=[TemplateIn(id="t", name="x", questions=["  "])]))
    dup = [TemplateIn(id="t", name="a", questions=["q"]),
           TemplateIn(id="t", name="b", questions=["q"])]
    with pytest.raises(HTTPException, match="重复"):
        put_prompt_templates(PromptTemplatesIn(items=dup))
    with pytest.raises(HTTPException, match="过多"):
        put_prompt_templates(PromptTemplatesIn(items=[
            TemplateIn(id=f"t{i}", name=f"n{i}", questions=["q"]) for i in range(31)]))


def test_prompt_templates_in_settings_api(tmp_db):
    """GET 全量带出模板组(前端渲染数据源)。"""
    import urllib.request
    from fastapi.testclient import TestClient  # noqa: F401  S6 遗留面;此处仍走直调
    from app.routers.settings_api import read_settings
    data = read_settings()
    assert data["prompt_templates"] == {"items": []}
