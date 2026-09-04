"""记账管道(F13/F14 落点):AgentRun + AiUsageLog。

约定(任务书 §3/§6):
- 每次一次完整的 AI 动作 = 一条 agent_run + N 条 ai_usage_log;
- action 区分记账口径(单章成本 vs 审稿对话 vs 查证),不混账;
- 金额 = token 数 × 价格基准(设置页 pricing 组),币种人民币元。
"""
from __future__ import annotations

import json
import time
from datetime import date
import uuid
from typing import Any

from ..common import _now
from ..db import tx
from ..settings_store import get_settings


def start_run(
    action: str,
    *,
    project_id: str | None = None,
    node_id: str | None = None,
    agent_type: str = "system",
    input_summary: str | None = None,
) -> str:
    run_id = f"run_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        conn.execute(
            "INSERT INTO agent_runs(id, project_id, node_id, action, agent_type, status,"
            " input_summary, started_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, project_id, node_id, action, agent_type, "running",
             input_summary, _now(), _now()),
        )
    return run_id


def finish_run(
    run_id: str,
    *,
    status: str = "succeeded",
    output_summary: str | None = None,
    error_message: str | None = None,
) -> None:
    with tx() as conn:
        conn.execute(
            "UPDATE agent_runs SET status=?, output_summary=?, error_message=?, finished_at=?"
            " WHERE id=?",
            (status, output_summary, error_message, _now(), run_id),
        )


def resolve_thinking_level(action: str, model: str) -> str | None:
    """按 action 解析思考档位(low/high/max);不该注入时返回 None。

    注入需同时满足:
    - thinking.enabled 为真(总开关,可一键回到模型原生行为);
    - 模型名命中 model_match——reasoning_effort 是 GLM 系参数,
      对不认识的厂商传过去会 400,故按模型名白名单注入;
    - 解析结果是合法档位。

    settings 里 llm.extra 若显式写了 reasoning_effort,以 extra 为准(见 chat_completion)。
    """
    th = get_settings()["thinking"]
    if not th.get("enabled"):
        return None
    match = str(th.get("model_match") or "").lower()
    if match and match not in (model or "").lower():
        return None
    level = (th.get("by_action") or {}).get(action) or th.get("default")
    return level if level in ("low", "high", "max") else None


def price_for(model: str) -> tuple[float, float]:
    """返回 (input_per_m, output_per_m),元/百万 token;未命中模型用 default。

    双份价格(2026-09-03 拍板):discount_until(含当天)过期后自动用 standard 正价,
    未配置或未过期用 default——到期免手工切换,成本不失真。"""
    pricing = get_settings()["pricing"]
    std, until = pricing.get("standard"), pricing.get("discount_until")
    if std and until:
        try:
            if date.today().isoformat() > str(until):
                return (float(std.get("input_per_m", 0)), float(std.get("output_per_m", 0)))
        except ValueError:
            pass
    for entry in pricing.get("models", []):
        if entry.get("model") == model:
            return float(entry.get("input_per_m", 0)), float(entry.get("output_per_m", 0))
    d = pricing.get("default", {})
    return float(d.get("input_per_m", 0)), float(d.get("output_per_m", 0))


def log_usage(
    run_id: str,
    *,
    provider: str,
    model: str,
    action: str,
    request_tokens: int,
    response_tokens: int,
    duration_ms: int,
    project_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """落一条 AiUsageLog;金额按价格基准现算,返回落库行(含 cost)供调用方展示。"""
    in_price, out_price = price_for(model)
    cost_request = request_tokens / 1_000_000 * in_price
    cost_response = response_tokens / 1_000_000 * out_price
    cost_total = cost_request + cost_response
    row = {
        "id": f"usage_{uuid.uuid4().hex[:20]}",
        "request_tokens": request_tokens,
        "response_tokens": response_tokens,
        "cost_request": round(cost_request, 6),
        "cost_response": round(cost_response, 6),
        "cost_total": round(cost_total, 6),
    }
    with tx() as conn:
        conn.execute(
            "INSERT INTO ai_usage_logs(id, run_id, project_id, provider, model, action,"
            " request_tokens, response_tokens, cost_request, cost_response, cost_total,"
            " duration_ms, target_type, target_id, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], run_id, project_id, provider, model, action,
             request_tokens, response_tokens, row["cost_request"], row["cost_response"],
             row["cost_total"], duration_ms, target_type, target_id, _now()),
        )
    return row


def chat_completion(
    messages: list[dict[str, str]],
    *,
    action: str,
    role: str = "default",
    project_id: str | None = None,
    node_id: str | None = None,
    agent_type: str = "chat",
    input_summary: str | None = None,
    max_tokens_override: int | None = None,
    temperature_override: float | None = None,
) -> dict[str, Any]:
    """一次带记账的完整对话调用:agent_run + ai_usage_log 自动落库。

    供各功能统一走此入口,保证"每次调用自动落账"(M1 判据)。
    max_tokens_override:个别动作(如一键构建的长 JSON)需要超出设置页的输出上限时使用。
    node_id:章节语境调用传入,agent_runs 落列供驾驶舱按章聚合成本
    (实跑 2026-09-02 拍板 #5;此前全表 None 导致成本列恒 0)。
    """
    from ..llm.client import get_client, get_role_params

    run_id = start_run(action, project_id=project_id, node_id=node_id,
                       agent_type=agent_type, input_summary=input_summary)
    params = get_role_params(role)
    if max_tokens_override:
        params["max_tokens"] = max_tokens_override
    if temperature_override is not None:
        params["temperature"] = temperature_override
    # 厂商扩展参数原样透传;思考档位按 action 注入,extra 里显式写的不覆盖
    extra_body = dict(params.pop("extra") or {})
    thinking_level = resolve_thinking_level(action, params["model"])
    if thinking_level and "reasoning_effort" not in extra_body:
        extra_body["reasoning_effort"] = thinking_level
    t0 = time.monotonic()
    try:
        # 免费档模型限流常见:429 退避重试(5s/15s 两轮),其余异常不重试
        from openai import RateLimitError

        resp = None
        for attempt, backoff in enumerate((0, 5, 15)):
            if backoff:
                time.sleep(backoff)
            try:
                resp = get_client().chat.completions.create(
                    **({"extra_body": extra_body} if extra_body else {}),
                    model=params["model"],
                    messages=messages,
                    temperature=params["temperature"],
                    max_tokens=params["max_tokens"],
                )
                break
            except RateLimitError:
                if attempt == 2:
                    raise
        duration_ms = int((time.monotonic() - t0) * 1000)
        usage = getattr(resp, "usage", None)
        request_tokens = getattr(usage, "prompt_tokens", 0) or 0
        response_tokens = getattr(usage, "completion_tokens", 0) or 0
        content = resp.choices[0].message.content or ""
        usage_row = log_usage(
            run_id,
            provider="openai-compatible",
            model=params["model"],
            action=action,
            request_tokens=request_tokens,
            response_tokens=response_tokens,
            duration_ms=duration_ms,
            project_id=project_id,
        )
        # 档位入 output_summary:事后回查"这章到底跑的哪一档"全靠这行
        _th = f",思考 {thinking_level}" if thinking_level else ""
        finish_run(run_id, status="succeeded",
                   output_summary=f"{len(content)} 字回包,模型 {params['model']}{_th}")
        return {
            "run_id": run_id,
            "content": content,
            "model": params["model"],
            "duration_ms": duration_ms,
            "usage": usage_row,
        }
    except Exception as exc:
        finish_run(run_id, status="failed", error_message=str(exc)[:2000])
        raise


def summarize_messages(messages: list[dict[str, str]], limit: int = 200) -> str:
    """把消息压成一行摘要,供 agent_runs.input_summary。"""
    parts = []
    for m in messages:
        text = (m.get("content") or "")[:limit]
        parts.append(f"[{m.get('role','user')}] {text}")
    return json.dumps(parts, ensure_ascii=False)[:2000]
