"""设置页 API(F15):模型/价格基准/预算/装配上限占位 + API key。

api_key 单独走 POST /api/settings/api-key,落 secrets.local.json(git 忽略),
GET 永远不回传 key 本体,只回传"是否已配置"。

大文件拆分批(2026-09-10,纯移动零行为变化):MCP 域(put_mcp/import_mcp+敏感字段
剥离)抽至 settings_mcp.py,参考提示词库域(put_reference_prompts+三层绑定)抽至
settings_refprompts.py——两件挂子路由(无 prefix),本件 include_router 叠加
/api/settings,URL 零变化;refprompts 三符号 re-export 保测试导入路径。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import tx
from ..llm.atomic_io import write_json_atomic
from ..settings_store import (
    SECRETS_PATH, get_api_key, get_settings, get_touch_registry, set_api_key,
    update_settings,
)
from .settings_mcp import mcp_router  # noqa: F401  子路由挂载(本文件尾部 include)
from .settings_refprompts import (  # noqa: F401  纯移动 re-export:保测试导入路径
    ReferencePromptsIn,
    RefPromptItem,
    put_reference_prompts,
)
from .settings_refprompts import refprompts_router

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
        "ui": get_settings()["ui"],
        "touches": get_settings()["touches"],               # 批次六甲:用户覆盖项
        "touches_registry": get_touch_registry(),           # 批次六甲:登记全录(设置页表头)
        "prompt_templates": get_settings()["prompt_templates"],  # 自定义预设模板(填空式)
        "output_limits": get_settings()["output_limits"],   # 输出上下限三层(2026-09-09)
        "reference_prompts": get_settings()["reference_prompts"],  # 参考提示词库+绑定
        "api_key_set": bool(get_api_key()),
    }


class LlmIn(BaseModel):
    provider_name: str | None = None
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    extra: dict | None = None


@router.put("/llm")
def put_llm(body: LlmIn) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("llm", patch)
    return {"ok": True, "llm": get_settings()["llm"]}


# ── 模型切换器(体感 2026-09-06,参考竞品服务商卡:免手动填三件套)────────
# 预设=三件套(路由/模型/key 名);切换即:存档当前 key → 换目标商 key → 换 llm 组。
_LLM_PRESETS: dict[str, dict] = {
    "glm": {"label": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-5.3-flash", "key_name": "glm_api_key"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com",
                 "model": "deepseek-v4-flash", "key_name": "deepseek_api_key"},
    # 批次七①:千章测评主模型(思考链关走 llm.extra={"enable_thinking": false} 透传)
    "qwen": {"label": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "model": "qwen3.8-flash", "key_name": "qwen_api_key"},
}
# SECRETS_PATH 取 settings_store 正本(勿自算路径——曾因少一层指到 backend/data,热修 cc162f5)
_SECRETS_PATH = SECRETS_PATH


def _read_secrets() -> dict:
    try:
        return json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@router.get("/llm-presets")
def llm_presets() -> dict:
    cur = get_settings()["llm"]
    active = next((k for k, v in _LLM_PRESETS.items() if v["base_url"] == cur.get("base_url")), None)
    sec = _read_secrets()
    return {"presets": [{"key": k, **v,
                         "key_ready": bool(sec.get(v["key_name"])),
                         "active": k == active} for k, v in _LLM_PRESETS.items()],
            "current": cur}


class SwitchIn(BaseModel):
    provider: str


@router.post("/llm-switch")
def llm_switch(body: SwitchIn) -> dict:
    """一键切换服务商三件套;当前 key 存档为 <旧商>_api_key 备换回。"""
    preset = _LLM_PRESETS.get(body.provider)
    if preset is None:
        raise HTTPException(422, f"未知服务商: {body.provider}(可选 {'/'.join(_LLM_PRESETS)})")
    sec = _read_secrets()
    target_key = sec.get(preset["key_name"], "")
    if not target_key:
        raise HTTPException(409, f"{preset['label']} 的 key 未配置(secrets.{preset['key_name']})")
    # 存档当前生效 key:按当前 base_url 反查商名,没匹配上就存 prev_api_key
    cur = get_settings()["llm"]
    prev = next((k for k, v in _LLM_PRESETS.items() if v["base_url"] == cur.get("base_url")), None)
    stash_name = _LLM_PRESETS[prev]["key_name"] if prev else "prev_api_key"
    if sec.get("api_key"):
        sec[stash_name] = sec["api_key"]
    sec["api_key"] = target_key
    # 原子写(审计 2026-09-06 S4):与 settings_store._update_secrets 同纪律,
    # 半写文件会毁掉全部 key 存档
    write_json_atomic(_SECRETS_PATH, sec)
    update_settings("llm", {"provider_name": body.provider,
                            "base_url": preset["base_url"], "model": preset["model"]})
    return {"ok": True, "llm": get_settings()["llm"]}


# ── 二期⑧:温度预设三档(用户拍板"做成预设,不用我手测";随时切换)──
TEMPERATURE_PRESETS: dict[str, dict] = {
    "steady": {"label": "稳健", "temperature": 0.5, "top_p": None},
    "standard": {"label": "标准", "temperature": 0.7, "top_p": None},
    "inspire": {"label": "灵感", "temperature": 1.0, "top_p": 0.95},
}


@router.get("/temperature-presets")
def temperature_presets() -> dict:
    cur = get_settings()["llm"]
    active = next((k for k, v in TEMPERATURE_PRESETS.items()
                   if abs(cur.get("temperature", 0) - v["temperature"]) < 1e-6
                   and ((cur.get("top_p") is None and v["top_p"] is None)
                        or (cur.get("top_p") is not None and v["top_p"] is not None
                            and abs(cur["top_p"] - v["top_p"]) < 1e-6))), None)
    return {"presets": [{"key": k, **v, "active": k == active}
                        for k, v in TEMPERATURE_PRESETS.items()],
            "current": {"temperature": cur.get("temperature"), "top_p": cur.get("top_p")}}


@router.put("/temperature-preset")
def put_temperature_preset(body: SwitchIn) -> dict:
    """温度预设一键切换(key=steady/standard/inspire);与模型切换器同款一键语义。"""
    preset = TEMPERATURE_PRESETS.get(body.provider)
    if preset is None:
        raise HTTPException(422, f"未知温度预设: {body.provider}"
                                 f"(可选 {'/'.join(TEMPERATURE_PRESETS)})")
    update_settings("llm", {"temperature": preset["temperature"], "top_p": preset["top_p"]})
    return {"ok": True, "preset": {"key": body.provider, **preset}}


@router.post("/llm-test")
def llm_test() -> dict:
    """检测连接:走统一记账管道真实调用(chat_test 档)——成本入台账、429 退避、
    思考档位注入与正式调用同款(审计 2026-09-06 S3:原实现直连 SDK 完全绕过记账,
    注释却称"如实入台账")。批次六甲: touches.llm_test 的 model/max_tokens 在此
    生效(独立触点键,不污染 chat_test 对话线)。"""
    from ..ledger.usage import chat_completion
    from ..settings_store import get_touch_overrides
    ov = get_touch_overrides("llm_test")
    try:
        r = chat_completion(
            [{"role": "user", "content": "reply: OK"}],
            action="chat_test", touches_off=True,   # 检测连接=测当前三件套,吃 llm_test 触点而非 chat_test
            # 512:思考型模型给足思考空间,否则 content 为空
            max_tokens_override=ov.get("max_tokens") or 512)
        return {"ok": True, "model": r["model"],
                "reply": r["content"][:40],
                "tokens": [r["usage"]["request_tokens"], r["usage"]["response_tokens"]]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


class PriceEntry(BaseModel):
    model: str | None = None  # models 组必填;default/standard 组无 model(defaulter 曾因此 422)
    input_per_m: float
    output_per_m: float
    cache_input_per_m: float | None = None          # 缓存命中输入价(未配=同输入价)
    peak_input_per_m: float | None = None           # 峰谷三价(配 peak_schedule 生效)
    peak_output_per_m: float | None = None
    peak_cache_input_per_m: float | None = None
    peak_schedule: str | None = None                # 形如 "mon-fri 09-12,14-18"(北京时)


class PricingIn(BaseModel):
    default: PriceEntry | None = None
    models: list[PriceEntry] | None = None
    standard: PriceEntry | None = None       # 正价(折扣到期自动启用);显式传 null 清除
    discount_until: str | None = None        # 折扣最后有效日 YYYY-MM-DD(含当天)


@router.put("/pricing")
def put_pricing(body: PricingIn) -> dict:
    patch: dict = {}
    if body.default is not None:
        patch["default"] = body.default.model_dump()
    if body.models is not None:
        patch["models"] = [m.model_dump() for m in body.models]
    # standard/discount_until 用 model_fields_set 区分"未传"与"显式传 null"——
    # null = 清除该字段(审计 2026-09-06 S8:原实现 null 被跳过,注释与行为不符)
    if "standard" in body.model_fields_set:
        patch["standard"] = body.standard.model_dump() if body.standard is not None else None
    if "discount_until" in body.model_fields_set:
        patch["discount_until"] = body.discount_until or None
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
    body_inject: bool | None = None   # WPS 大纲:节点 body 装配注入(默认关,任务词拍板②)


# 自定义预设模板(2026-09-09 拍板"选择填空式"):防御上限=30 模板×每模板 10 问×
# 每问 120 字,防异常输入撑爆设置与 system 注入
TEMPLATE_MAX = 30
QUESTIONS_PER_TEMPLATE_MAX = 10
QUESTION_MAX_LEN = 120


class TemplateIn(BaseModel):
    id: str
    name: str
    questions: list[str]


class PromptTemplatesIn(BaseModel):
    items: list[TemplateIn]


@router.put("/prompt-templates")
def put_prompt_templates(body: PromptTemplatesIn) -> dict:
    """全量替换(镜像 put_touches 语义);结构校验就地,零配置=空列表。"""
    if len(body.items) > TEMPLATE_MAX:
        raise HTTPException(422, f"模板过多(上限 {TEMPLATE_MAX} 个)")
    seen: set[str] = set()
    for t in body.items:
        name = t.name.strip()
        if not name:
            raise HTTPException(422, "模板名称不能为空")
        if len(name) > 30:
            raise HTTPException(422, f"模板名称过长(上限 30 字): {name[:20]}…")
        if t.id in seen:
            raise HTTPException(422, f"模板 id 重复: {t.id}")
        seen.add(t.id)
        if len(t.questions) > QUESTIONS_PER_TEMPLATE_MAX:
            raise HTTPException(422, f"模板「{name}」问题过多(上限 {QUESTIONS_PER_TEMPLATE_MAX} 条)")
        cleaned: list[str] = []
        for q in t.questions:
            q = q.strip()
            if not q:
                continue
            if len(q) > QUESTION_MAX_LEN:
                raise HTTPException(422, f"问题过长(上限 {QUESTION_MAX_LEN} 字): {q[:20]}…")
            cleaned.append(q)
        if not cleaned:
            raise HTTPException(422, f"模板「{name}」至少要有一条问题")
        t.questions[:] = cleaned
    update_settings("prompt_templates", {
        "items": [t.model_dump() for t in body.items]})
    return {"ok": True, "prompt_templates": get_settings()["prompt_templates"]}


@router.put("/assembly")
def put_assembly(body: AssemblyIn) -> dict:
    # 装配上限(设置页可调,默认 6000 字符);装配管道按此裁剪按需条目(见 assembly.py);
    # body_inject=WPS 大纲节点正文注入开关(默认关=老书零破坏)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("assembly", patch)
    return {"ok": True, "assembly": get_settings()["assembly"]}


class LimitPair(BaseModel):
    min_tokens: int | None = None
    max_tokens: int | None = None


class BookLimits(BaseModel):
    default: LimitPair | None = None
    actions: dict[str, LimitPair] | None = None


class OutputLimitsIn(BaseModel):
    """输出上下限三层(2026-09-09 拍板)。零值防御:0/负数视为 null(=未配置)。"""
    default: LimitPair | None = None
    books: dict[str, BookLimits] | None = None


def _clean_pair(p: LimitPair | None) -> dict | None:
    if p is None:
        return None
    out: dict[str, int | None] = {}
    for k in ("min_tokens", "max_tokens"):
        v = getattr(p, k)
        out[k] = v if (v and v > 0) else None
    return out


@router.put("/output-limits")
def put_output_limits(body: OutputLimitsIn) -> dict:
    patch: dict = {}
    if body.default is not None:
        patch["default"] = _clean_pair(body.default)
    if body.books is not None:
        books: dict = {}
        for pid, b in body.books.items():
            books[pid] = {"default": _clean_pair(b.default),
                          "actions": {a: _clean_pair(p) for a, p in (b.actions or {}).items()}}
        patch["books"] = books
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("output_limits", patch)
    return {"ok": True, "output_limits": get_settings()["output_limits"]}


# ── 参考提示词库:整域已抽至 settings_refprompts.py(2026-09-10 拆分,include 挂载)──

@router.post("/backup-now")
def backup_now_endpoint() -> dict:
    """立即快照(候选清单落地批 B):与每日守护同一 backup_now,落 data/backups。"""
    from ..backup import backup_now
    dest = backup_now()
    return {"ok": True, "file": dest.name}


@router.post("/push-backup")
def push_backup() -> dict:
    """推送到备份仓 beifen(手动;子进程 git push,60s 超时,结果回显)。"""
    import subprocess

    repo = Path(__file__).resolve().parents[3]   # 仓库根
    try:
        r = subprocess.run(
            ["git", "push", "beifen", "main"], cwd=repo,
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace")
        tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()][-3:]
        return {"ok": r.returncode == 0, "code": r.returncode,
                "output": "\n".join(tail) or "(无输出)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "output": "推送超时(60s);稍后可重试"}


class UiIn(BaseModel):
    auto_compact: bool | None = None
    organizer_enabled: bool | None = None


@router.put("/ui")
def put_ui(body: UiIn) -> dict:
    # 界面组(批次三⑤):auto_compact=对话超 40 条自动拼前情提要;工程信息开关在前端
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    update_settings("ui", patch)
    return {"ok": True, "ui": get_settings()["ui"]}


class TouchesIn(BaseModel):
    touches: dict[str, dict[str, Any]] = {}   # {action: {prompt_append?, model?, max_tokens?}}


@router.put("/touches")
def put_touches(body: TouchesIn) -> dict:
    """批次六甲:触点覆盖项保存。语义=**全量替换**(前端传全量已覆盖 map)——
    update_settings 是合并语义,直接用它删除项会被旧值还魂,故整组直写;
    校验=键须在 TOUCHES 登记、max_tokens≥64 整数,模型可用性交"检测连接"。"""
    from ..settings_store import TOUCHES
    import json as _json
    llm = get_settings()["llm"]
    base = (llm.get("base_url") or "").lower()
    provider_key = "deepseek" if "deepseek" in base else (
        "glm" if "bigmodel" in base or "glm" in base else None)
    clean: dict[str, dict[str, Any]] = {}
    for key, item in (body.touches or {}).items():
        if key not in TOUCHES:
            raise HTTPException(422, f"未知触点:{key}")
        entry: dict[str, Any] = {}
        pa = item.get("prompt_append")
        if isinstance(pa, str) and pa.strip():
            entry["prompt_append"] = pa
        m = item.get("model")
        if isinstance(m, str) and m.strip():
            m = m.strip()
            # 任务词甲件红队②:模型须属当前 provider(跨厂商网关必拒;实测 DeepSeek 拒 glm 名)
            if provider_key and provider_key not in m.lower():
                raise HTTPException(
                    422, f"{key}.model={m} 不属于当前服务商({llm.get('base_url')});"
                         f"请先切服务商,或留空使用当前三件套模型")
            entry["model"] = m
        mt = item.get("max_tokens")
        if mt is not None:
            if isinstance(mt, bool) or not isinstance(mt, int) or mt < 64:
                raise HTTPException(422, f"{key}.max_tokens 须为 ≥64 的整数")
            entry["max_tokens"] = mt
        if entry:
            clean[key] = entry
    now = datetime.now(timezone.utc).isoformat()
    with tx() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES('touches', ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (_json.dumps(clean, ensure_ascii=False), now))
    get_settings()   # 热生效直查库,此处仅触发一次读取确认
    return {"ok": True, "touches": get_settings()["touches"]}


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


# ── MCP 服务器预留区:整域已抽至 settings_mcp.py(2026-09-10 拆分,include 挂载)──

# 子路由挂载(尾部 include;路径与本文件各端点无重叠,注册顺序对外零变化)
router.include_router(mcp_router)
router.include_router(refprompts_router)
