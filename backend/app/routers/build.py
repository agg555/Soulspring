"""AI 一键构建提案(F2):把书的核心信息变成整套 L1 设定草案。

纪律:
- 只在用户点按钮时运行——本模块是全系统唯一的"生成设定"入口,无任何自动触发;
- 产出一律走 l1.create_ai_proposals 落提案区(写入协议),人批准才入正式区;
- 走统一记账管道 action='build_proposal',与单章成本/审稿对话分账;
- 单次成本超过预算告警线时在响应中带 warning(风险 8:超限提示)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..db import tx
from ..ledger.usage import chat_completion
from ..llm.atomic_io import write_text_atomic
from ..settings_store import get_settings
from .l1 import SCHEMA, create_ai_proposals
from .l1 import EntryIn

router = APIRouter(prefix="/api/books", tags=["build"])

# __file__ = backend/app/routers/build.py → parents[3] = 仓库根
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "构建-一键提案.md"

FIELD_LABELS = {
    c["key"]: {f["key"]: f["label"] for f in c["fields"]} for c in SCHEMA["categories"]
}
CATEGORY_LABELS = {c["key"]: c["label"] for c in SCHEMA["categories"]}


def _load_book(pid: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "书不存在")
    book = dict(row)
    for k in ("tropes", "style"):
        try:
            book[k] = json.loads(book.get(k) or "[]")
        except (json.JSONDecodeError, TypeError):
            book[k] = []
    return book


def _book_info_block(book: dict) -> str:
    lines = [
        f"书名:{book.get('name') or '(未定)'}",
        f"主角:{book.get('protagonist') or '(未定)'}",
        f"类型:{book.get('genre') or '(未定)'}",
        f"流派标签:{'、'.join(book.get('tropes') or []) or '(未定)'}",
        f"受众:{book.get('audience') or '(未定)'}",
        f"风格:{'、'.join(book.get('style') or []) or '(未定)'}",
        f"情节结构:{book.get('plot_mode') or '(未定)'}",
        f"力量体系预设:{book.get('power_preset') or '(未定)'}",
        f"金手指预设:{book.get('cheat_preset') or '(未定)'}",
        f"每章字数:{book.get('chapter_words') or '(未定)'}",
        f"目标总字数:{book.get('target_words') or '(未定)'}",
        f"核心冲突/创作方向:{book.get('core_conflict') or '(未定)'}",
        f"简介:{book.get('description') or '(未定)'}",
    ]
    return "\n".join(lines)


def _schema_block() -> str:
    lines = []
    for c in SCHEMA["categories"]:
        fields = "、".join(f["label"] for f in c["fields"])
        lines.append(f"- {c['key']}({c['label']}):字段 = {fields}")
    return "\n".join(lines)


def _parse_proposals(raw: str) -> list[dict]:
    """解析模型输出:容忍 ```json 围栏;要求 JSON 数组。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        head = text[:150].replace("\n", "\\n")
        raise HTTPException(502, f"模型输出不是合法 JSON({exc});开头内容: {head}…可重试")
    if not isinstance(data, list):
        raise HTTPException(502, "模型输出应为 JSON 数组")
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(item)
    return out


@router.post("/{pid}/build/propose")
def build_propose(pid: str) -> dict:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    if "{{BOOK_INFO}}" not in template or "{{SCHEMA}}" not in template:
        raise HTTPException(500, "构建提示词模板缺少占位符")
    book = _load_book(pid)
    system = template.replace("{{BOOK_INFO}}", _book_info_block(book)).replace(
        "{{SCHEMA}}", _schema_block())
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "请生成整套设定草案,严格按系统指令输出 JSON。"}]
    try:
        result = chat_completion(
            messages, action="build_proposal", agent_type="builder",
            project_id=pid, input_summary=f"一键构建提案: {book.get('name')}",
            max_tokens_override=32000,  # GLM 始终思考且思考量大:32000 才能装下思考+完整 JSON(实测 16k 会截断)
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"模型调用失败:{exc}")

    raw_items = _parse_proposals(result["content"])
    proposals = []
    for item in raw_items:
        cat = str(item.get("category", "")).strip()
        if cat not in CATEGORY_LABELS:  # 风格指纹及其他未知类别一律丢弃
            continue
        fields_in = item.get("fields") or {}
        clean_fields = {
            k: str(v) for k, v in fields_in.items() if k in FIELD_LABELS[cat]
        }
        proposals.append(EntryIn(
            category=cat, name=str(item.get("name", "")).strip(),
            fields=clean_fields, notes=str(item.get("notes", ""))))
    if not proposals:
        raise HTTPException(502, "模型未产出任何有效条目(类别须为六类之一);可重试")

    created = create_ai_proposals(pid, proposals)
    budget = get_settings()["budget"]["chat_turn_alert"]
    resp = {
        "ok": True,
        "run_id": result["run_id"],
        "usage": result["usage"],
        "count": created["count"],
        "parsed_raw": len(raw_items),
        "dropped": len(raw_items) - len(proposals),
    }
    if result["usage"]["cost_total"] > budget:
        resp["warning"] = (
            f"本次构建成本 ¥{result['usage']['cost_total']:.4f} 超过单次预算告警线 ¥{budget:.2f}")
    return resp
