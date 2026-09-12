"""记账管道(F13/F14 落点):AgentRun + AiUsageLog。

约定(任务书 §3/§6):
- 每次一次完整的 AI 动作 = 一条 agent_run + N 条 ai_usage_log;
- action 区分记账口径(单章成本 vs 审稿对话 vs 查证),不混账;
- 金额 = token 数 × 价格基准(设置页 pricing 组),币种人民币元。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
import uuid
from typing import Any

from ..common import _now
from ..db import tx
from ..settings_store import TOUCHES, get_settings, get_touch_overrides


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


def _apply_thinking(extra_body: dict, thinking_level: str | None,
                    action: str, model: str) -> None:
    """思考档位→厂商参数(批次三⑤新增"关"档,纯函数可测)。

    DeepSeek:只有开关无 effort(API 规格,审计 S5 实查 chevoink ai-service.ts:304)
    ——low/high/max 等效 enabled,"off"=显式 disabled(非思考,机械活提速 2-4 倍)。
    GLM 系:强制思考不可关,"off"回落动作默认档(执行书拍板 6)。
    extra 里显式写的 reasoning_effort 不覆盖(用户手工配置优先)。
    """
    m = (model or "").lower()
    if thinking_level == "off":
        if "deepseek" in m:
            extra_body["thinking"] = {"type": "disabled"}
        elif m.find("glm") != -1 or get_settings()["thinking"].get("model_match", "glm") in m:
            # GLM 强制思考不可关:回落动作默认档;解析不出(总开关关)则不发,防 null 参数
            level = resolve_thinking_level(action, model)
            if level:
                extra_body["reasoning_effort"] = level
        return
    if thinking_level and "reasoning_effort" not in extra_body:
        if "deepseek" in m:
            extra_body["thinking"] = {"type": "enabled"}
        elif m.find("glm") != -1 or get_settings()["thinking"].get("model_match", "glm") in m:
            extra_body["reasoning_effort"] = thinking_level


def price_for(model: str, now: datetime | None = None) -> tuple[float, float, float]:
    """返回 (input_per_m, output_per_m, cache_input_per_m),元/百万 token;未命中模型用 default。

    双份价格(2026-09-03 拍板):discount_until(含当天)过期后,未登记模型自动改用
    standard 正价,未配置或未过期用 default——到期免手工切换,成本不失真。
    **models 逐模型条目不受折扣期影响,始终按自身价**(2026-09-06 审计 H1 修正:原实现
    过期后提前 return,把 DeepSeek 等在册模型也错记成 GLM 正价)。
    缓存输入价(成本控制移植,2026-09-06):models 条目可带 cache_input_per_m
    (如 DeepSeek 空闲命中 0.05);未配置=与输入同价(不误算)。
    峰谷:条目可带 peak_schedule(如 "mon-fri 09-12,14-18")与 peak_* 三价,
    Asia/Shanghai 当前时刻落在高峰窗即用 peak 价;now 可注入(终审修复 2026-09-07:
    峰谷测试曾依赖真实时刻,周一峰窗内必碎——与 _in_peak_window 同款固时钟)。"""
    pricing = get_settings()["pricing"]
    std, until = pricing.get("standard"), pricing.get("discount_until")
    expired_std: tuple[float, float, float] | None = None
    if std and until:
        try:
            if date.today().isoformat() > str(until):
                expired_std = (float(std.get("input_per_m", 0)), float(std.get("output_per_m", 0)),
                               float(std.get("cache_input_per_m", std.get("input_per_m", 0))))
        except ValueError:
            pass
    for entry in pricing.get("models", []):
        if entry.get("model") == model:
            in_p, out_p = float(entry.get("input_per_m", 0)), float(entry.get("output_per_m", 0))
            cache_p = float(entry.get("cache_input_per_m", in_p))
            sched = str(entry.get("peak_schedule") or "")
            if sched and _in_peak_window(sched, now):
                return (float(entry.get("peak_input_per_m", in_p)),
                        float(entry.get("peak_output_per_m", out_p)),
                        float(entry.get("peak_cache_input_per_m", cache_p)))
            return in_p, out_p, cache_p
    if expired_std is not None:
        return expired_std
    d = pricing.get("default", {})
    return (float(d.get("input_per_m", 0)), float(d.get("output_per_m", 0)),
            float(d.get("cache_input_per_m", d.get("input_per_m", 0))))


def _in_peak_window(schedule: str, now: datetime | None = None) -> bool:
    """峰谷判定(移植 chevoink 成本适配思路):schedule 形如 "mon-fri 09-12,14-18"。

    以 Asia/Shanghai(UTC+8)为准;解析失败视为非高峰(宁便宜不错贵)。
    """
    try:
        # Asia/Shanghai = UTC+8 固定偏移(中国无夏令时);用 aware now 消 utcnow 弃用告警
        now = now or datetime.now(timezone(timedelta(hours=8)))
        parts = schedule.split(maxsplit=1)
        if len(parts) != 2:
            return False
        day_part, hour_part = parts
        weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        d0, _, d1 = day_part.partition("-")
        wd = now.weekday()   # 0=Monday
        i0, i1 = weekdays.index(d0.strip()[:3].lower()), weekdays.index(d1.strip()[:3].lower())
        if not (i0 <= wd <= i1 if i0 <= i1 else wd >= i0 or wd <= i1):
            return False
        hm = now.hour + now.minute / 60
        for seg in hour_part.split(","):
            a, _, b = seg.strip().partition("-")
            if float(a) <= hm < float(b):
                return True
        return False
    except (ValueError, KeyError):
        return False


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
    cached_tokens: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """落一条 AiUsageLog;金额按价格基准现算,返回落库行(含 cost)供调用方展示。

    cached_tokens:命中缓存的请求 token 数(批次二速赢,体感 2026-09-05"命中/未命中
    概率显示");厂商不给该字段时保持 0。
    """
    in_price, out_price, cache_price = price_for(model, now)
    # 成本控制移植(chevoink 适配,2026-09-06):命中部分按缓存价,未命中按输入价
    cached = min(max(0, cached_tokens), request_tokens)
    cost_request = ((request_tokens - cached) / 1_000_000 * in_price
                    + cached / 1_000_000 * cache_price)
    cost_response = response_tokens / 1_000_000 * out_price
    cost_total = cost_request + cost_response
    row = {
        "id": f"usage_{uuid.uuid4().hex[:20]}",
        "request_tokens": request_tokens,
        "response_tokens": response_tokens,
        "cached_tokens": cached_tokens,
        "cost_request": round(cost_request, 6),
        "cost_response": round(cost_response, 6),
        "cost_total": round(cost_total, 6),
    }
    with tx() as conn:
        conn.execute(
            "INSERT INTO ai_usage_logs(id, run_id, project_id, provider, model, action,"
            " request_tokens, response_tokens, cached_tokens, cost_request, cost_response,"
            " cost_total, duration_ms, target_type, target_id, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], run_id, project_id, provider, model, action,
             request_tokens, response_tokens, cached_tokens,
             row["cost_request"], row["cost_response"],
             row["cost_total"], duration_ms, target_type, target_id, _now()),
        )
    return row


def _pos(v) -> int | None:
    """正整数过滤(2026-09-09 上下限防御:0/负数/非整数=未配置)。"""
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _resolve_max_tokens(action: str, *, touch_max: int | None,
                        project_id: str | None = None) -> int | None:
    """上限生效链纯函数(2026-09-09 三层拍板):书×触点 > 书默认 > 触点 touches
    > 全局默认 > 出厂登记。0/负数视为未配置(防御,正常入口已清洗)。
    零配置返回登记值(与既有链路等价)。"""
    ol = get_settings().get("output_limits") or {}
    book_ol = (ol.get("books") or {}).get(project_id or "") or {}
    ba_ol = (book_ol.get("actions") or {}).get(action) or {}
    reg_max = _pos((TOUCHES.get(action) or {}).get("max_tokens"))   # 登记默认=原硬编码实值收编
    return (_pos(ba_ol.get("max_tokens"))
            or _pos((book_ol.get("default") or {}).get("max_tokens"))
            or _pos(touch_max)
            or _pos((ol.get("default") or {}).get("max_tokens"))
            or reg_max)


def _resolve_min_tokens(action: str, project_id: str | None = None) -> int | None:
    """下限告警线生效链:书×触点 > 书默认 > 全局默认;无配置/0/负数=None(不告警)。"""
    ol = get_settings().get("output_limits") or {}
    book_ol = (ol.get("books") or {}).get(project_id or "") or {}
    ba_ol = (book_ol.get("actions") or {}).get(action) or {}
    return (_pos(ba_ol.get("min_tokens"))
            or _pos((book_ol.get("default") or {}).get("min_tokens"))
            or _pos((ol.get("default") or {}).get("min_tokens")))


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
    thinking_override: str | None = None,   # 对话台思考档直选(体感 2026-09-06)
    touches_off: bool = False,              # 批次六甲:禁用触点覆盖(llm_test 检测连接专用,
                                            # 防 chat_test 触点模型污染"测当前三件套"的用途)
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
    # 批次六甲:触点级覆盖(分层=运行时 override>触点 touches>登记默认>role 默认)——
    # model 覆盖须在 _apply_thinking 之前(厂商判定随覆盖后模型);上限仅在调用方
    # 未显式传 override 时生效。模型可用性由设置页"检测连接"负责,失败走全局异常壳。
    ov = {} if touches_off else get_touch_overrides(action)
    if ov.get("model"):
        params["model"] = ov["model"]
    # 输出上下限三层体系(2026-09-09 拍板,解析链见 _resolve_max_tokens/_resolve_min_tokens;
    # 下限=告警线,回包低于下限在返回体标 limit_warning,调用方决定呈现位置)。
    min_tokens = _resolve_min_tokens(action, project_id)
    if not max_tokens_override:
        effective_max = _resolve_max_tokens(action, touch_max=ov.get("max_tokens"),
                                            project_id=project_id)
        if effective_max:
            params["max_tokens"] = effective_max
    if temperature_override is not None:
        params["temperature"] = temperature_override
    # 厂商扩展参数原样透传;思考档位按 action 注入,extra 里显式写的不覆盖。
    # DeepSeek 对话类默认关思考(2026-09-09 实锤:reasoning 吃满登记上限 8000,
    # content 空 ¥0.037/次,对话不可用;对话类按"新动作先省档"拍板精神默认非思考,
    # 对话台直选档位仍可覆盖)。
    extra_body = dict(params.pop("extra") or {})
    thinking_level = thinking_override or resolve_thinking_level(action, params["model"])
    if thinking_override is None and thinking_level is None \
            and "deepseek" in (params["model"] or "").lower() \
            and (TOUCHES.get(action) or {}).get("kind") == "dialog":
        thinking_level = "off"
    _apply_thinking(extra_body, thinking_level, action, params["model"])
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
                    **({"top_p": params["top_p"]} if params.get("top_p") is not None else {}),
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
        # 缓存命中折算(2026-09-06 自研净化实现,替代批次三的 chevoink 参考版;
        # 行为依据=各家 API 规格这一事实:GLM/OpenAI 兼容网关报
        # prompt_tokens_details.cached_tokens(显式 0 是有效观测,不能当字段缺失),
        # DeepSeek 原生报 hit/miss 两个计数(只报其一时用 prompt 总数倒推另一个)。
        # 统一产出"命中 token 数",并以请求总数封顶防脏数据。
        details = getattr(usage, "prompt_tokens_details", None)
        compatible = getattr(details, "cached_tokens", None)
        ds_hit = getattr(usage, "prompt_cache_hit_tokens", None)
        ds_miss = getattr(usage, "prompt_cache_miss_tokens", None)
        if compatible is not None:
            hit = int(compatible)
        elif ds_hit is not None:
            hit = int(ds_hit)
        elif ds_miss is not None:
            hit = max(0, request_tokens - int(ds_miss))
        else:
            hit = 0
        cached_tokens = max(0, min(hit, request_tokens))
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
            cached_tokens=cached_tokens,
        )
        # 档位入 output_summary:事后回查"这章到底跑的哪一档"全靠这行
        _th = f",思考 {thinking_level}" if thinking_level else ""
        finish_run(run_id, status="succeeded",
                   output_summary=f"{len(content)} 字回包,模型 {params['model']}{_th}")
        # 下限告警线(2026-09-09 拍板):低于下限只标注不拦截(API 无硬下限,
        # 模型侧截断/空回包/敷衍由人按提示处置);0 回包不在此处重复报
        # (空回包已有专属可读提示)。
        limit_warning = None
        if min_tokens and 0 < response_tokens < min_tokens:
            limit_warning = f"本次输出 {response_tokens} token,低于下限 {min_tokens}(疑似截断或敷衍回包)"
        return {
            "run_id": run_id,
            "content": content,
            "model": params["model"],
            "duration_ms": duration_ms,
            "usage": usage_row,
            "limit_warning": limit_warning,
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
