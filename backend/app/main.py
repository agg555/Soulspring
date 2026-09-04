"""Soulspring 后端入口。

形态(任务书 §3):本地单用户 FastAPI 服务,静态托管 frontend/dist,
双击 scripts/启动.bat 拉起并自动开浏览器。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import migrate
from .routers import (
    adopt, books, branches, build, chaishu, conversations, dashboard, graphs, l1, l2,
    links, overview, outline, review, settings_api, usage_api, workbench,
)

app = FastAPI(title="Soulspring", version="0.1.0")

# 本地单用户,同源部署为主;CORS 仅放开本机回环,便于前端 dev server 联调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router)
app.include_router(books.router)
app.include_router(links.router)
app.include_router(l1.router)
app.include_router(outline.router)
app.include_router(workbench.router)
app.include_router(l2.router)
app.include_router(review.router)
app.include_router(adopt.router)
app.include_router(branches.router)
app.include_router(conversations.router)
app.include_router(dashboard.router)
app.include_router(graphs.router)
app.include_router(chaishu.router)
app.include_router(build.router)
app.include_router(settings_api.router)
app.include_router(usage_api.router)


@app.on_event("startup")
def _startup() -> None:
    migrate()


FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.api_route("/{full_path:path}", include_in_schema=False, methods=["GET", "HEAD"])
def spa(full_path: str):
    """静态托管 + SPA 回退;API 路由优先于本兜底。"""
    # 防 ../、\、绝对路径等变体逃出 dist:resolve 后必须仍落在 dist 内
    target = (FRONTEND_DIST / full_path).resolve()
    if target.is_file() and target.is_relative_to(FRONTEND_DIST):
        return FileResponse(target)
    return FileResponse(FRONTEND_DIST / "index.html")
