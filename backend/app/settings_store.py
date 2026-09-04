"""设置存储(F15 落点)。

- 非 secret 设置存 settings 表(KV + JSON),每次读取直查库 → 改配置即生效,无需重启;
- api_key 存 data/secrets.local.json(git 忽略),绝不入库、绝不进 git。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import DATA_DIR, tx

SECRETS_PATH = DATA_DIR / "secrets.local.json"

# 默认值:首次启动即有完整形状,设置页在其上覆盖
DEFAULTS: dict[str, dict[str, Any]] = {
    "llm": {
        "provider_name": "default",
        "base_url": "https://api.openai.com/v1",
        "model": "",
        "temperature": 0.7,
        "max_tokens": 2048,
        # 厂商扩展参数(整个 JSON 原样透传给 API body,如 GLM 的 {"thinking":{"type":"disabled"}})
        "extra": {},
    },
    # 价格基准:按模型名给单价(元 / 百万 token);未命中模型用 default
    "pricing": {
        "default": {"input_per_m": 0.0, "output_per_m": 0.0},
        "models": [],
        # 双份价格(2026-09-03 拍板):折扣期存 discount_until(YYYY-MM-DD,含当天),
        # 过期后 price_for 自动改用 standard(正价)——到期不手工切换也不失真。
        "standard": None,          # {"input_per_m":..,"output_per_m":..} 正价,可空
        "discount_until": None,    # 折扣最后有效日(含),可空
    },
    "budget": {
        "per_chapter_alert": 0.25,  # 任务书 §6:单章 AI 成本告警线
        "chat_turn_alert": 1.0,     # 审稿对话单次预算上限(风险 8)
    },
    # 思考档位(GPU 预算闸门):按 action 分档注入 reasoning_effort
    # 背景(2026-08-30 实测):glm-5.3-flash 强制思考且不可关闭,思考 token 按输出价
    # ¥8/M 计费;同一任务 low 档比默认档省约 90%、快约 6 倍。故按动作分档而非全局一刀切。
    "thinking": {
        "enabled": True,             # 总开关:关掉则完全不注入,回到模型原生行为
        "model_match": "glm",        # 只对模型名含此串的注入(小写匹配),避免非 GLM 厂商 400
        "default": "high",           # 未列出的 action 走此档
        # 档位取值:low / high / max(该模型不支持 disabled)
        "by_action": {
            # 机械活:提取、摘要、规整 → 便宜快跑
            "chaishu_summary": "low",      # 拆书章节摘要(用户拍板:拆书用 low)
            "l2_rewrite_draft": "low",     # L2 回写 diff 起草
            "chapter_normalize": "low",    # 字数规整
            "chat_test": "low",            # 连通性测试
            "outline_chat": "low",         # 大纲节点对话(执行书:新对话类 action 一律先 low,不够再升)
            "book_chat": "low",            # 书级对话(骨架批执行书 §2:thinking 先 low)
            # 创作与审美活:要质量 → 深度思考
            "chapter_plan": "max",         # 写章计划卡
            "chapter_draft": "max",        # 章节草稿(用户拍板:写文用 max)
            "chapter_repair": "max",       # 审计后 AI 自修
            "chapter_review": "max",       # LLM 层评审
            "review_chat": "max",          # 审稿对话台
            "build_proposal": "max",       # 一键构建提案
        },
    },
    "assembly": {
        # 装配上限(字符):2026-08-30 拍板"可配置,默认 6000";inkflow 实践 2000 为下限参照
        "token_limit": 6000,
    },
    "workbench": {
        "repair_on_audit_fail": True,   # 审计不过后提供"AI 自修一轮"按钮(拍板:灵活,可关)
        "normalizer": True,             # 字数规整器(±20% 自动压/扩一次,拍板:采纳,可关)
        "llm_review": True,             # 评审报告随草稿生成(免费模型可常开)
        "chapter_min": 1500,            # 目标字数下限(规整器与审计共用)
        "chapter_max": 3000,            # 目标字数上限
    },
    # MCP 白名单制(任务书 §3):只列允许拉起的服务端;命令必须在本白名单内
    "mcp": {
        "servers": [
            {"name": "wiki-zh", "command": "wikipedia-mcp", "args": ["--transport", "stdio", "--language", "zh"]},
            {"name": "wiki-en", "command": "wikipedia-mcp", "args": ["--transport", "stdio", "--language", "en"]},
        ],
        "search_fallback": "tavily",    # 旧系统纪律:wiki 优先,失败降级 tavily
    },
    # 技能(需求稿 2026-08-31):全局默认 + 单本书覆盖;值为 prompts/技能/ 目录名,""= 不启用。
    # 解析优先级:运行时手选 > book_overrides[pid] > global_default > 不启用。
    # book_overrides 值语义:技能名 = 该书默认;"" = 该书强制不启用;缺键 = 跟随全局。
    "skills": {
        "global_default": "",
        "book_overrides": {},
    },
    # 大纲精修(第二批 C1):场景级显隐开关——关闭时树与现状四级一致;场景不进章节状态机
    "outline": {
        "scenes_enabled": False,
    },
    # 驾驶舱质量分权重(B4,执行书原第三批):合成分 = 加权和,critical 一票否决仅展示;
    # 只展示留痕,不改任何既有闸门。各分量先归一到 0-10:评审七维均分(0-10)、
    # 朱雀人工%(0-100 → /10)、成本分 = clamp(10×(1-单章成本/告警线), 0, 10)
    "dashboard": {
        "w_review": 0.5,
        "w_zhuque": 0.3,
        "w_cost": 0.2,
    },
}


def get_settings() -> dict[str, dict[str, Any]]:
    """读全量设置(默认值 ∪ 库中覆盖),热生效:不缓存。

    thinking.by_action 特殊处理:库中存的是旧时刻的完整档位表,浅合并会把
    DEFAULTS 新增的 action 默认档(如 outline_chat=low)整键吃掉——对 by_action
    再做一层键级合并(DEFAULTS 打底,库值优先),保证"新增动作先 low"的拍板不丢。
    """
    merged = {k: dict(v) for k, v in DEFAULTS.items()}
    with tx() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        key = row["key"]
        if key not in merged:
            continue
        try:
            data = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if key == "thinking" and isinstance(data.get("by_action"), dict):
            by_action = dict(DEFAULTS["thinking"]["by_action"])
            by_action.update(data["by_action"])
            data["by_action"] = by_action
        merged[key].update(data)
    return merged


def resolve_skill(pid: str, explicit: str | None = None) -> str:
    """技能三档解析:运行时手选 > 单本书覆盖 > 全局默认;空串=不启用。"""
    skills = get_settings()["skills"]
    if explicit is not None:
        return explicit
    override = (skills.get("book_overrides") or {}).get(pid)
    if override is not None:
        return override
    return skills.get("global_default") or ""


def update_settings(group: str, patch: dict[str, Any]) -> None:
    """按组合并写入;未知组拒绝,防设置页拼错键。"""
    if group not in DEFAULTS:
        raise ValueError(f"unknown settings group: {group}")
    from datetime import datetime, timezone

    current = dict(DEFAULTS[group])
    with tx() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (group,)).fetchone()
        if row:
            try:
                current.update(json.loads(row["value"]))
            except (json.JSONDecodeError, TypeError):
                pass
        current.update(patch)
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (group, json.dumps(current, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )


def get_api_key() -> str:
    if not SECRETS_PATH.exists():
        return ""
    try:
        return json.loads(SECRETS_PATH.read_text(encoding="utf-8")).get("api_key", "")
    except (json.JSONDecodeError, OSError):
        return ""


def set_api_key(key: str) -> None:
    """原子写 secrets 文件;合并保留既有键(MCP 密钥等),绝不整体覆盖。"""
    _update_secrets({"api_key": key})


def _update_secrets(patch: dict) -> None:
    """secrets 文件合并写:已知键(api_key/mcp)保留,只更新 patch 覆盖的键。"""
    import json as _json

    from .llm.atomic_io import write_json_atomic

    current: dict = {}
    if SECRETS_PATH.exists():
        try:
            current = _json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current = {}
    current.update(patch)
    write_json_atomic(SECRETS_PATH, current)


def get_mcp_secrets(name: str) -> dict:
    """取某 MCP 服务端的敏感字段(headers/env/api_key);未配置返回空表。"""
    if not SECRETS_PATH.exists():
        return {}
    try:
        data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return (data.get("mcp") or {}).get(name) or {}


def set_mcp_secrets(name: str, secrets: dict) -> None:
    """存某 MCP 服务端的敏感字段(api_key/headers/env 等,git 忽略)。"""
    import json as _json

    from .llm.atomic_io import write_json_atomic

    current: dict = {}
    if SECRETS_PATH.exists():
        try:
            current = _json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current = {}
    mcp = current.get("mcp") or {}
    if secrets:
        mcp[name] = secrets
    else:
        mcp.pop(name, None)
    current["mcp"] = mcp
    write_json_atomic(SECRETS_PATH, current)
