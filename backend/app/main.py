"""Soulspring 后端入口。

形态(任务书 §3):本地单用户 FastAPI 服务,静态托管 frontend/dist,
双击 scripts/启动.bat 拉起并自动开浏览器。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .stability import log_error

from .db import migrate
from .routers import (
    adopt, books, branches, build, chaishu, chapter_card, conversations, dashboard,
    diagnostics, graphs, ideas, l1, l2, links, overview, outline, outline_ai, review,
    search, settings_api, templates, usage_api, workbench,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """启动时迁移(替代弃用的 @app.on_event,审计 2026-09-06 S12)+每日备份守护。"""
    migrate()
    from .backup import start_backup_daemon
    start_backup_daemon()
    yield


app = FastAPI(title="Soulspring", version="0.1.0", lifespan=_lifespan)


@app.exception_handler(Exception)
async def uncaught_exception_handler(request: Request, exc: Exception):
    """批次四①:未捕获异常兜底(分级)——原始栈+请求上下文落 data/logs,用户只见统一壳。

    HTTPException 不进此 handler(FastAPI 自带 detail 语义不变);
    红队修正:不回 exc 内容防内部信息泄漏,真因以日志为准。"""
    import traceback

    log_error(
        f"[{request.method} {request.url.path}] 未捕获异常: {type(exc).__name__}: {exc}\n"
        + "".join(traceback.format_exception(exc)))
    return JSONResponse(status_code=500, content={
        "detail": "服务内部错误,已记录日志(data/logs);请重试,持续出现请把日志发给作者"})

# 本地单用户,同源部署为主;CORS 仅放开本机回环,便于前端 dev server 联调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8600", "http://localhost:8600"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 批次四④:Origin/CSRF 校验(池 E 区清偿)────────────────────────────
# 写请求(POST/PUT/PATCH/DELETE)的 Origin/Referer 必须命中本机白名单;两者皆缺
# 放行(非浏览器客户端:curl/脚本);命中失败 403。GET/HEAD 不校验(无副作用)。
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_CSRF_PORT = os.environ.get("SOULSPRING_PORT", "8600")
_CSRF_ALLOWED_NETLOC = {
    f"127.0.0.1:{_CSRF_PORT}", f"localhost:{_CSRF_PORT}",
    "127.0.0.1:5173", "localhost:5173",   # Vite dev server
}


def origin_allowed(url: str) -> bool:
    """Origin 或 Referer 统一按 netloc 判定——Referer 带路径不能误杀(终审修复 2026-09-07)。"""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    if parts.scheme != "http":
        return False
    return parts.netloc.lower() in _CSRF_ALLOWED_NETLOC


@app.middleware("http")
async def origin_csrf_guard(request: Request, call_next):
    if request.method in _CSRF_METHODS:
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        if origin and not origin_allowed(origin):
            return JSONResponse(status_code=403,
                                content={"detail": "跨站请求被拒绝(Origin 校验失败)"})
    return await call_next(request)

app.include_router(overview.router)
app.include_router(books.router)
app.include_router(links.router)
app.include_router(l1.router)
app.include_router(outline.router)
app.include_router(outline_ai.router)
app.include_router(workbench.router)
app.include_router(l2.router)
app.include_router(review.router)
app.include_router(adopt.router)
app.include_router(branches.router)
app.include_router(conversations.router)
app.include_router(dashboard.router)
app.include_router(diagnostics.router)
app.include_router(graphs.router)
app.include_router(chaishu.router)
app.include_router(build.router)
app.include_router(settings_api.router)
app.include_router(usage_api.router)
app.include_router(search.router)
app.include_router(templates.router)
app.include_router(ideas.router)
app.include_router(chapter_card.router)


FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.api_route("/{full_path:path}", include_in_schema=False, methods=["GET", "HEAD"])
def spa(full_path: str):
    """静态托管 + SPA 回退;API 路由优先于本兜底。"""
    # 防 ../、\、绝对路径等变体逃出 dist:resolve 后必须仍落在 dist 内
    target = (FRONTEND_DIST / full_path).resolve()
    if target.is_file() and target.is_relative_to(FRONTEND_DIST):
        return FileResponse(target)
    return FileResponse(FRONTEND_DIST / "index.html")
