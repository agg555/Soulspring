"""MCP 查证(F12;2026-09-10 自 chaishu.py 抽出,纯移动零行为变化——大工程②A)。

- 查证链:wiki 优先(MCP 官方 SDK stdio 白名单制)→ tavily 降级(旧系统纪律);
- 取证落素材库 evidence_items(来源/时间/置信度);
- 本件挂自己的子路由(同前缀 /api/chaishu),chaishu.py include_router 后
  URL 与注册顺序对外部零变化。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx
from ..settings_store import get_settings

# 子路由不带 prefix(父 router.include_router 会叠加自己的 /api/chaishu 前缀)
verify_router = APIRouter(tags=["chaishu"])


@verify_router.get("/mcp/status")
def mcp_status() -> dict:
    mcp = get_settings()["mcp"]
    key_ok = "tavily_api_key" in _secrets()
    return {"whitelist": mcp.get("servers", []), "fallback": mcp.get("search_fallback"),
            "tavily_key_configured": key_ok}


def _secrets() -> dict:
    from ..settings_store import SECRETS_PATH
    if not SECRETS_PATH.exists():
        return {}
    return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """tavily 降级通道(旧系统纪律);HTTP API 直连。"""
    key = _secrets().get("tavily_api_key", "")
    if not key:
        raise HTTPException(409, "未配置 tavily key(设置页/素材库降级不可用)")
    # Mimosa 高危整改(2026-09-06):SSRF 防护——http.client 固定主机直连,
    # 无 URL 变量拼接面(主机/路径字面常量)。
    import http.client as _hc
    payload = json.dumps({"api_key": key, "query": query, "max_results": max_results,
                          "search_depth": "basic"}).encode()
    conn = _hc.HTTPSConnection("api.tavily.com", timeout=30)
    try:
        conn.request("POST", "/search", body=payload,
                     headers={"Content-Type": "application/json",
                              "Host": "api.tavily.com"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
    finally:
        conn.close()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "content": (x.get("content") or "")[:800],
             "confidence": x.get("score", 0.5)} for x in data.get("results", [])]


def _wiki_mcp_search(query: str, lang: str) -> list[dict]:
    """MCP 基座:官方 SDK stdio 白名单制调用。"""
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = next((s for s in get_settings()["mcp"]["servers"]
                   if s["name"] == f"wiki-{lang}"), None)
    if server is None:
        raise HTTPException(403, f"服务端 {lang} 不在白名单内")
    command = str((Path(__file__).resolve().parent.parent / ".venv" / "Scripts" /
                   f"{server['command']}.exe").resolve())

    async def run() -> list[dict]:
        params = StdioServerParameters(command=command, args=server["args"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("search_wikipedia",
                                            {"query": query, "limit": 5})
                for c in r.content:
                    t = getattr(c, "text", None)
                    if t:
                        try:
                            data = json.loads(t)
                            return [{"title": x.get("title", ""), "url": x.get("url", ""),
                                     "content": (x.get("snippet") or x.get("extract") or "")[:800],
                                     "confidence": 0.7} for x in data.get("results", [])]
                        except json.JSONDecodeError:
                            continue
                return []

    return asyncio.run(run())


class VerifyIn(BaseModel):
    project_id: str
    query: str
    lang: str = "zh"


@verify_router.post("/verify")
def verify(body: VerifyIn) -> dict:
    """查证:wiki 优先 → tavily 降级 → 结果落素材库(来源/时间/置信度)。"""
    t0 = time.monotonic()
    results, via = [], ""
    try:
        results = _wiki_mcp_search(body.query, body.lang)
        via = f"wiki-{body.lang}"
    except HTTPException:
        raise
    except Exception:
        results = []
    if not results:
        results = _tavily_search(body.query)
        via = "tavily"
    duration_ms = int((time.monotonic() - t0) * 1000)
    saved = []
    with tx() as conn:
        for x in results:
            eid = f"ev_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO evidence_items(id, project_id, query, source, url, content,"
                " confidence, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (eid, body.project_id, body.query, via, x.get("url", ""),
                 x.get("content", ""), x.get("confidence", 0.5), _now()))
            saved.append(eid)
    return {"ok": True, "via": via, "count": len(saved), "duration_ms": duration_ms,
            "results": results}


@verify_router.get("/evidence")
def evidence_list(project_id: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT query, source, url, content, confidence, created_at FROM evidence_items"
            " WHERE project_id=? ORDER BY created_at DESC LIMIT 50", (project_id,)).fetchall()]
    return {"evidence": rows}
