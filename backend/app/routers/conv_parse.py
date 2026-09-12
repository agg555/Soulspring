"""对话回包解析器(A1 建议协议三级兜底;2026-09-10 从 conversations.py 抽出,
纯移动零行为变化——大工程②去繁化简:解析逻辑独立成模块,便于单测与维护)。

三级兜底(实锤 2026-09-09:模型在 JSON 字符串里输出裸换行致整条降级,原文照显=
JSON 壳+字面 \n,体感极差):①宽松截取 {..} 常规解析;②strict=False 容忍字符串内
裸控制字符(实测救活裸换行场景);③正则抽 "reply" 值当正文(suggestions 丢弃,
只服务呈现);全败才降级纯文本(parse_error=True,原文完整保留——模型没按协议说
人话时,原样显示本就正确)。
"""
from __future__ import annotations

import json
import re

from .generation import _parse_json_loose

# 建议 target_type 白名单(与 REPLY_PROTOCOL 协议一致;新目标类型须同步登记)
SUGGESTION_TARGET_TYPES = ("none", "chapter_text", "outline_field", "event_field",
                           "graph_field", "graph_add", "subtopic_add")

# 三级兜底第③层:非贪婪抽 "reply" 值(到 , "suggestions" 或串尾)
_REPLY_FIELD_RE = re.compile(r'"reply"\s*:\s*"(.*?)"(?:\s*,\s*"suggestions"|$)', re.DOTALL)


def _between_braces(text: str) -> str:
    """截取首个 { 到末个 } 的片段(找不到或逆序则原样返回,交由 json 报错)。"""
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return text
    return text[s:e + 1]


def _extract_reply_field(raw: str) -> str | None:
    m = _REPLY_FIELD_RE.search(raw)
    if m is None:
        return None
    text = m.group(1).replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').strip()
    return text or None


def parse_reply(raw: str) -> tuple[str, list[dict], bool]:
    """解析模型回包 → (reply 正文, 建议列表, parse_error)。见模块 docstring 三级兜底。"""
    data: dict | None = None
    for attempt in (_parse_json_loose, lambda t: json.loads(_between_braces(t), strict=False)):
        try:
            data = attempt(raw)
            break
        except (ValueError, json.JSONDecodeError):
            continue
    if isinstance(data, dict):
        reply = str(data.get("reply", "") or "").strip()
        raw_suggestions = data.get("suggestions")
        if not isinstance(raw_suggestions, list):
            raw_suggestions = []
        if reply or raw_suggestions:
            clean: list[dict] = []
            for s in raw_suggestions[:10]:
                if not isinstance(s, dict):
                    continue
                tt = s.get("target_type")
                clean.append({
                    "quote": str(s.get("quote") or ""),
                    "issue": str(s.get("issue") or ""),
                    "suggestion": str(s.get("suggestion") or ""),
                    "severity": s.get("severity") if s.get("severity") in ("minor", "major", "critical") else "minor",
                    "target_type": tt if tt in SUGGESTION_TARGET_TYPES else "none",
                    "target": s.get("target") if isinstance(s.get("target"), dict) else {},
                })
            return reply, clean, False
    rescued = _extract_reply_field(raw)
    if rescued:
        return rescued, [], True
    return raw.strip(), [], True
