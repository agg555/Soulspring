"""项目总览(F13 雏形):项目列表 + 今日/本月成本。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import tx

router = APIRouter(prefix="/api/overview", tags=["overview"])


def _today_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _month_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@router.get("")
def overview() -> dict:
    today, month = _today_prefix(), _month_prefix()
    with tx() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT id, name, genre, description, status, created_at, updated_at"
            " FROM projects ORDER BY created_at DESC").fetchall()]
        cost = conn.execute(
            "SELECT"
            " COALESCE(SUM(CASE WHEN created_at LIKE ? THEN cost_total END),0) AS today_cost,"
            " COALESCE(SUM(CASE WHEN created_at LIKE ? THEN cost_total END),0) AS month_cost,"
            " COALESCE(SUM(CASE WHEN created_at LIKE ? THEN 1 END),0) AS today_calls"
            " FROM ai_usage_logs",
            (today + "%", month + "%", today + "%"),
        ).fetchone()
    return {
        "projects": projects,
        "today_cost": round(cost["today_cost"], 4),
        "month_cost": round(cost["month_cost"], 4),
        "today_calls": cost["today_calls"],
    }


class ProjectIn(BaseModel):
    name: str
    genre: str | None = None
    description: str | None = None
    protagonist: str | None = None
    tropes: list[str] | None = None
    audience: str | None = None
    style: list[str] | None = None
    plot_mode: str | None = None
    power_preset: str | None = None
    cheat_preset: str | None = None
    core_conflict: str | None = None
    chapter_words: int | None = None
    target_words: int | None = None


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn) -> dict:
    if not body.name.strip():
        raise HTTPException(422, "书名不能为空")
    now = datetime.now(timezone.utc).isoformat()
    pid = f"proj_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, genre, description, protagonist, tropes,"
            " audience, style, plot_mode, power_preset, cheat_preset, core_conflict,"
            " chapter_words, target_words, status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'active', ?, ?)",
            (
                pid, body.name.strip(), body.genre, body.description, body.protagonist,
                json.dumps(body.tropes or [], ensure_ascii=False),
                body.audience,
                json.dumps(body.style or [], ensure_ascii=False),
                body.plot_mode, body.power_preset, body.cheat_preset, body.core_conflict,
                body.chapter_words, body.target_words, now, now,
            ),
        )
    return {"id": pid, "name": body.name.strip()}
