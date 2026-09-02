"""设置页 API(F15):模型/价格基准/预算/装配上限占位 + API key。

api_key 单独走 POST /api/settings/api-key,落 secrets.local.json(git 忽略),
GET 永远不回传 key 本体,只回传"是否已配置"。
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..settings_store import (
    get_api_key, get_settings, set_api_key, set_mcp_secrets, update_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def read_settings() -> dict:
    return {
        "llm": get_settings()["llm"],
        "pricing": get_settings()["pricing"],
        "budget": get_settings()["budget"],
        "assembly": get_settings()["assembly"],
        "thinking": get_settings()["thinking"],
        "skills": get_settings()["skills"],
        "mcp": get_settings()["mcp"],
        "outline": get_settings()["outline"],
        "dashboard": get_settings()["dashboard"],
        "api_key_set": bool(get_api_key()),
    }


class LlmIn(BaseModel):
    provider_name: str | None = None
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra: dict | None = None


@router.put("/llm")
def put_llm(body: LlmIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("llm", patch)
    return {"ok": True, "llm": get_settings()["llm"]}


class PriceEntry(BaseModel):
    model: str
    input_per_m: float
    output_per_m: float


class PricingIn(BaseModel):
    default: PriceEntry | None = None
    models: list[PriceEntry] | None = None


@router.put("/pricing")
def put_pricing(body: PricingIn) -> dict:
    patch: dict = {}
    if body.default is not None:
        patch["default"] = body.default.model_dump()
    if body.models is not None:
        patch["models"] = [m.model_dump() for m in body.models]
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("pricing", patch)
    return {"ok": True, "pricing": get_settings()["pricing"]}


class BudgetIn(BaseModel):
    per_chapter_alert: float | None = None
    chat_turn_alert: float | None = None


@router.put("/budget")
def put_budget(body: BudgetIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("budget", patch)
    return {"ok": True, "budget": get_settings()["budget"]}


class AssemblyIn(BaseModel):
    token_limit: int | None = None


@router.put("/assembly")
def put_assembly(body: AssemblyIn) -> dict:
    # 装配上限(设置页可调,默认 6000 字符);装配管道按此裁剪按需条目(见 assembly.py)
    update_settings("assembly", {"token_limit": body.token_limit})
    return {"ok": True, "assembly": get_settings()["assembly"]}


class WorkbenchIn(BaseModel):
    repair_on_audit_fail: bool | None = None
    normalizer: bool | None = None
    llm_review: bool | None = None
    chapter_min: int | None = None
    chapter_max: int | None = None


@router.put("/workbench")
def put_workbench(body: WorkbenchIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("workbench", patch)
    return {"ok": True, "workbench": get_settings()["workbench"]}


class ThinkingIn(BaseModel):
    enabled: bool | None = None
    model_match: str | None = None
    default: str | None = None
    by_action: dict[str, str] | None = None


@router.put("/thinking")
def put_thinking(body: ThinkingIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    # 档位取值校验:写错档位只会在真实调用时炸,提前挡掉
    for key, level in list((patch.get("by_action") or {}).items()) + (
            [("default", patch["default"])] if "default" in patch else []):
        if level not in ("low", "high", "max"):
            raise HTTPException(422, f"{key} 档位非法:{level}(只可 low/high/max)")
    update_settings("thinking", patch)
    return {"ok": True, "thinking": get_settings()["thinking"]}


class ApiKeyIn(BaseModel):
    api_key: str


@router.put("/api-key")
def put_api_key(body: ApiKeyIn) -> dict:
    set_api_key(body.api_key.strip())
    return {"ok": True, "api_key_set": True}


# ── 大纲精修(第二批 C1):场景级显隐开关 ──

class OutlineIn(BaseModel):
    scenes_enabled: bool | None = None


@router.put("/outline")
def put_outline(body: OutlineIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("outline", patch)
    return {"ok": True, "outline": get_settings()["outline"]}


# ── 技能(需求3):全局默认;单本书覆盖走书籍信息页(PUT /api/books/{pid}) ──

class SkillsIn(BaseModel):
    global_default: str | None = None   # "" = 不启用;技能目录名


@router.put("/skills")
def put_skills(body: SkillsIn) -> dict:
    if body.global_default is not None:
        update_settings("skills", {"global_default": body.global_default.strip()})
    return {"ok": True, "skills": get_settings()["skills"]}


# ── MCP 服务器预留区(需求4):本期只存取与展示,零建连 ──

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


@router.put("/mcp")
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


@router.post("/mcp/import")
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
