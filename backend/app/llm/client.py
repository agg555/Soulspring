"""LLM 客户端管理。

移植自 inkflow(inkflow/core/llm_client.py,MIT License,
Copyright (c) 2026 ElysiaQWQ;详见 THIRD-PARTY-NOTICES.md),改动:
- 配置源从 model_settings.yaml 改为 DB 设置(settings_store,热生效);
- 单用户单默认路由(v0 无多角色路由表,role 仅作记账标签);
- 客户端缓存按 (base_url, api_key) 键,配置变更自动换新,无需失效调用。
"""
from __future__ import annotations

import threading
from typing import Any

from openai import OpenAI

from ..settings_store import get_api_key, get_settings

_lock = threading.Lock()
_client_cache: dict[tuple[str, str], OpenAI] = {}


def _resolve_route(role_name: str = "default") -> dict[str, Any]:
    """v0:全部角色走设置页的 llm 组;role 保留入参供记账与未来路由表扩展。"""
    settings = get_settings()
    return settings["llm"]


def get_client() -> OpenAI:
    api_key = get_api_key()
    base_url = _resolve_route().get("base_url") or "https://api.openai.com/v1"
    cache_key = (base_url, api_key)
    with _lock:
        client = _client_cache.get(cache_key)
        if client is None:
            if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
                # 不抛异常,让调用方拿到可读错误;设置页未配 key 是常态
                raise RuntimeError("API key 未配置:请到设置页填写后重试")
            # 显式超时:读 600s/连 15s;SDK 层不重试(429 退避由 ledger 统一管)。
            # 背景:2026-08-31 实测一次出站请求无限挂起,后台任务在 plan 阶段卡 15 分钟。
            client = OpenAI(api_key=api_key or "EMPTY", base_url=base_url,
                            timeout=600.0, max_retries=0)
            _client_cache[cache_key] = client
        return client


def get_role_params(role_name: str = "default") -> dict[str, Any]:
    route = _resolve_route(role_name)
    return {
        "model": route.get("model") or "",
        "temperature": float(route.get("temperature", 0.7)),
        "max_tokens": int(route.get("max_tokens", 2048)),
        "extra": route.get("extra") or {},
    }
