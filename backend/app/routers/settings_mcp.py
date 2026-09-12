"""MCP 服务器预留区(需求4):本期只存取与展示,零建连。

(2026-09-10 自 settings_api.py 抽出,纯移动零行为变化——大工程②A:
MCP 是设置页里最独立的一域,整表替换/JSON 导入/敏感字段剥离三件套同住;
子路由不带 prefix,settings_api include_router 叠加 /api/settings。)
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..settings_store import get_settings, set_mcp_secrets, update_settings

mcp_router = APIRouter(tags=["settings"])

SENSITIVE_KEY_RE = re.compile(r"key|token|secret|authorization", re.IGNORECASE)


def _sanitize_server(raw: dict) -> tuple[dict, dict]:
    """拆单条服务端配置:(非敏感骨架, 敏感字段包)。敏感字段进 secrets.local.json。"""
    server = {k: v for k, v in raw.items() if v not in (None, "", [])}
    secrets: dict = {}
    for field in ("headers", "env"):
        val = server.get(field)
        if isinstance(val, dict):
            picked = {k: v for k, v in val.items() if SENSITIVE_KEY_RE.search(k)}
            if picked:
                secrets[field] = picked
                server[field] = {k: v for k, v in val.items() if k not in picked}
    for field in ("api_key", "apiKey"):
        if field in server:
            secrets[field] = server.pop(field)
    if not server.get("name") or not str(server["name"]).strip():
        raise ValueError("每条服务端配置都需要非空 name")
    if server.get("transport") not in ("stdio", "http", None):
        raise ValueError(f"transport 只支持 stdio/http,得到:{server.get('transport')}")
    if server.get("transport") is None:
        # URL 型统一记 http(取值只有 stdio/http 两种,与 PUT 校验一致)
        server["transport"] = "http" if server.get("url") else "stdio"
    if server["transport"] == "http" and not server.get("url"):
        raise ValueError(f"http 型服务端「{server['name']}」缺 url")
    if server["transport"] == "stdio" and not server.get("command"):
        raise ValueError(f"stdio 型服务端「{server['name']}」缺 command")
    server["enabled"] = bool(server.get("enabled", False))   # 导入默认停用:预留不建连
    return server, secrets


def _validate_servers(servers: list) -> list[dict]:
    names = set()
    out = []
    for raw in servers:
        if not isinstance(raw, dict):
            raise ValueError("servers 应为对象数组")
        server, _ = _sanitize_server(raw)
        name = server["name"]
        if name in names:
            raise ValueError(f"服务端名重复:{name}")
        names.add(name)
        out.append(server)
    return out


class McpServersIn(BaseModel):
    servers: list[dict]


@mcp_router.put("/mcp")
def put_mcp(body: McpServersIn) -> dict:
    """整表替换 MCP 服务端列表(启停/删除走这里);只落 settings,不建连。"""
    try:
        servers = _validate_servers(body.servers)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    update_settings("mcp", {"servers": servers})
    return {"ok": True, "mcp": {"servers": get_settings()["mcp"]["servers"]}}


class McpImportIn(BaseModel):
    json_text: str


@mcp_router.post("/mcp/import")
def import_mcp(body: McpImportIn) -> dict:
    """导入通用 mcpServers JSON:{"mcpServers": {名: {command,args,env} | {url,headers}}}。

    兼容裸数组与直接对象数组;敏感字段(headers/env 里的 key/token/authorization、api_key)
    剥离进 data/secrets.local.json(git 忽略),settings 只存非敏感骨架。
    本期只落库不建连。
    """
    text = body.json_text.strip()
    if not text:
        raise HTTPException(422, "JSON 内容为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"不是合法 JSON:{exc}(请检查引号/逗号/花括号)")
    if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
        pairs = data["mcpServers"].items()
    elif isinstance(data, dict) and not any(k in data for k in ("servers", "mcpServers")):
        pairs = data.items()   # 允许省略外层键:{名称: {...}}
    elif isinstance(data, list):
        pairs = ((s.get("name", ""), s) for s in data)
    else:
        raise HTTPException(422, "无法识别的格式:需要 {\"mcpServers\":{…}}、{名称:{…}} 或数组")

    servers: list[dict] = []
    secrets_written = 0
    errors: list[str] = []
    for name, raw in pairs:
        if not isinstance(raw, dict):
            errors.append(f"「{name}」不是对象,已跳过")
            continue
        raw = dict(raw)
        raw.setdefault("name", str(name))
        try:
            server, secrets = _sanitize_server(raw)
        except ValueError as exc:
            errors.append(f"「{name}」:{exc};已跳过")
            continue
        servers.append(server)
        if secrets:
            set_mcp_secrets(server["name"], secrets)
            secrets_written += 1
    if not servers:
        raise HTTPException(422, "没有解析出任何有效服务端" + (";" + ";".join(errors) if errors else ""))

    existing = {s["name"]: s for s in get_settings()["mcp"]["servers"]}
    for s in servers:   # 同名覆盖,新名追加;不静默清空白名单
        existing[s["name"]] = s
    update_settings("mcp", {"servers": list(existing.values())})
    resp: dict = {"ok": True, "imported": len(servers),
                  "mcp": {"servers": get_settings()["mcp"]["servers"]}}
    if errors:
        resp["warnings"] = errors
    if secrets_written:
        resp["note"] = f"{secrets_written} 条含敏感字段,已剥离进 secrets.local.json(不入库不入 git)"
    return resp
