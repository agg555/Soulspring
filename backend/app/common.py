"""应用内公共小件(S3 单点化,审计 2026-09-01)。

时间戳/FRONTMATTER 解析/PROMPT 渲染/技能体加载/字段白名单:原本在各路由与
底层模块各有一份字面量实现,此处单点化后统一 import;纯移动,零行为变化。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

# 仓库根:backend/app/common.py → parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "prompts"
SKILLS_DIR = PROMPTS_DIR / "技能"

# 关系类别白名单:旧角色关系表用前 5 类;统一图谱引擎的边在前 5 类之上扩充
RELATION_KINDS = ("亲情", "爱情", "友情", "敌对", "其他")
EDGE_KINDS = (*RELATION_KINDS, "因果", "并行", "承接", "持有",
              "来源", "去向", "相邻", "通道", "从属", "同盟", "衍生", "克制", "自由")
# 剧情时间线事件可轻档写回的字段
EVENT_FIELDS = ("time_label", "title", "summary", "line", "status")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md 的 YAML frontmatter(仅 name/description 两键)。"""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            body = text[end + 3:].strip()
    return meta, body


def _prompt(name: str, replaces: dict[str, str]) -> str:
    """替换模板占位符;键允许带或不带 {{}} 双花括号。"""
    template = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    for key, val in replaces.items():
        token = key if key.startswith("{{") else "{{" + key + "}}"
        template = template.replace(token, val)
    return template


def _load_skill_body(key: str) -> str:
    f = SKILLS_DIR / key / "SKILL.md"
    if not f.exists():
        raise HTTPException(404, f"技能不存在:{key}")
    _, body = _parse_frontmatter(f.read_text(encoding="utf-8"))
    return body


def skill_section(skill: str | None) -> str:
    """生成处选技能(2026-08-31 需求稿):技能正文拼进提示词上下文;
    实跑 2026-09-02 由 generation._skill_section 上移公共——装配预览同口径使用。"""
    if not skill:
        return ""
    return f"## 启用技能:{skill}\n\n{_load_skill_body(skill)}"
