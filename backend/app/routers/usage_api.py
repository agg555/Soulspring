"""日志查看器(F14 雏形):AgentRun / AiUsageLog 只读回查。"""
from __future__ import annotations

from fastapi import APIRouter

from ..db import tx

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/logs")
def usage_logs(limit: int = 50) -> dict:
    limit = max(1, min(limit, 500))
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, run_id, model, action, request_tokens, response_tokens,"
            " cost_total, duration_ms, created_at"
            " FROM ai_usage_logs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    return {"logs": rows}


@router.get("/runs")
def agent_runs(limit: int = 50) -> dict:
    limit = max(1, min(limit, 500))
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, action, agent_type, status, input_summary, output_summary,"
            " error_message, started_at, finished_at"
            " FROM agent_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    return {"runs": rows}
