"""生成管道(S2 拆自 workbench.py,纯移动零行为变化)。

计划卡 → 草稿 → 规整器(_generate_draft_text/_normalize)→ LLM 七维度评审
(_llm_review,advisory 失败留痕)→ AI 自修一轮(_repair_once);
附 JSON 松解析(_parse_json_loose,对话建议协议同样复用)与技能/风格段组装。
"""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException

from ..assembly import assembled_text, build_assembly, get_chapter_plan, save_chapter_plan
from ..audit.anti_ai import build_anti_ai_prompt_section, check_dash_count, cleanup_dashes
from ..common import _now, _prompt, skill_section
from ..db import tx
from ..ledger.usage import chat_completion
from ..settings_store import get_settings
from .changeset_ops import (
    _carry_dismissals,
    _changeset_view,
    _code_audit,
    _open_changeset,
    _put_patch,
)


def _parse_json_loose(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        first = text.find("\n")
        last = text.rfind("```")
        if first != -1 and last > first:
            text = text[first + 1:last].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"输出中未找到 JSON 对象: {text[:80]}")
    return json.loads(text[start:end + 1])


def _book_style_section(pid: str) -> str:
    """风格段:风格指纹(若有)+ 向导风格标签。指纹为空时退化为标签。"""
    with tx() as conn:
        rows = conn.execute(
            "SELECT name, content FROM l1_entries WHERE project_id=? AND category='style_fingerprint'"
            " AND entry_status='confirmed'", (pid,)).fetchall()
        tags = conn.execute("SELECT genre, style FROM projects WHERE id=?", (pid,)).fetchone()
    lines = []
    for r in rows:
        lines.append(f"- {r['name']}: {r['content']}")
    if tags and tags["style"]:
        try:
            style = json.loads(tags["style"])
        except (json.JSONDecodeError, TypeError):
            style = []
        if style:
            lines.append("- 风格标签: " + "、".join(style))
    if not lines:
        return ""
    return "## 文风要求\n" + "\n".join(lines) + "\n"


def _generate_draft_text(pid: str, node: dict, *, force_new_plan: bool,
                         skill: str | None = None,
                         progress=None) -> tuple[str, dict, list[dict]]:
    """计划卡(缺失才生成)→ 草稿 → 规整器;返回 (草稿, 计划卡, 调用记录)。

    progress: 阶段回调(后台任务写 gen_tasks.stage 用);skill 非空时技能正文作为
    装配体附加段注入 {{ASSEMBLED}},并随装配日志留痕(source=skill + content_hash)。
    """
    wb = get_settings()["workbench"]
    notify = progress or (lambda _stage: None)
    plan = get_chapter_plan(node["id"])
    calls: list[dict] = []

    skill_text = skill_section(skill)
    extra_sections = None
    if skill_text:
        extra_sections = [{
            "source": "skill", "kind": "always", "title": f"技能:{skill}",
            "content": skill_text, "included": True,
            "content_hash": hashlib.sha1(skill_text.encode()).hexdigest()[:12],
        }]
    assembly = build_assembly(pid, node["id"], log=True, extra_sections=extra_sections)
    assembled = assembled_text(assembly)

    if not plan or force_new_plan:
        notify("plan")
        prompt = _prompt("章节-计划卡.md", {"{{ASSEMBLED}}": assembled})
        r = chat_completion(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": "请输出本章创作计划 JSON。"}],
            action="chapter_plan", project_id=pid, node_id=node["id"], agent_type="planner",
            # 输出预算 8000:该模型强制思考,思考 token 计入 completion_tokens;
            # 原 2000 会被思考链吃满,JSON 根本出不来(M6 实测输出 2000 而回包 0 字)
            input_summary=f"计划卡:{node['title']}", max_tokens_override=8000)
        calls.append(r)
        try:
            plan = _parse_json_loose(r["content"])
        except (ValueError, json.JSONDecodeError):
            plan = {}  # 计划卡失败不阻塞:留空计划以装配体直写
        save_chapter_plan(node["id"], plan)

    notify("draft")
    style = _book_style_section(pid)
    prompt = _prompt("章节-草稿.md", {
        "{{ASSEMBLED}}": assembled, "{{STYLE}}": style,
        "{{ANTI_AI}}": build_anti_ai_prompt_section(),
        "{{PLAN}}": json.dumps(plan, ensure_ascii=False, indent=1),
        "{{MIN}}": str(wb.get("chapter_min", 1500)), "{{MAX}}": str(wb.get("chapter_max", 3000)),
    })
    r = chat_completion(
        [{"role": "system", "content": prompt}, {"role": "user", "content": "开始撰写本章正文。"}],
        action="chapter_draft", project_id=pid, node_id=node["id"], agent_type="writer",
        # 24000:max 档思考可达 8-15K token,叠 2000 字正文约 3-4K;
        # 原 8192 实测被打满截断,正文 0 字
        input_summary=f"草稿:{node['title']}", max_tokens_override=24000)
    calls.append(r)
    draft = r["content"].strip()
    if check_dash_count(draft) > 4:
        draft = cleanup_dashes(draft, max_dashes=4)

    if wb.get("normalizer", True):
        notify("normalize")
        draft = _normalize(draft, calls, pid, node)
    return draft, plan, calls


def _normalize(draft: str, calls: list, pid: str, node: dict) -> str:
    wb = get_settings()["workbench"]
    lo = int(wb.get("chapter_min", 1500) * 0.8)
    hi = int(wb.get("chapter_max", 3000) * 1.2)
    count = len(draft)
    if lo <= count <= hi:
        return draft
    if count < lo:
        instruction = f"当前章节仅 {count} 字，目标 {wb.get('chapter_min')}-{wb.get('chapter_max')} 字。请扩展正文，补充场景描写、心理活动或对话，使总字数达标。保持情节和风格不变。"
    else:
        instruction = f"当前章节有 {count} 字，目标 {wb.get('chapter_min')}-{wb.get('chapter_max')} 字。请精简正文，去除冗余描写和重复对话。保持核心情节和亮点不变。"
    prompt = _prompt("章节-规整.md", {
        "{{DRAFT}}": draft, "{{INSTRUCTION}}": instruction,
        "{{MIN}}": str(wb.get("chapter_min", 1500)), "{{MAX}}": str(wb.get("chapter_max", 3000)),
    })
    r = chat_completion(
        [{"role": "system", "content": prompt}, {"role": "user", "content": "输出调整后的完整正文。"}],
        action="chapter_normalize", project_id=pid, node_id=node["id"], agent_type="writer",
        # 16000:规整走 low 档(思考近乎为 0),但要装下扩写后的完整正文
        input_summary=f"规整:{node['title']} ({count}字)", max_tokens_override=16000)
    calls.append(r)
    out = r["content"].strip()
    return cleanup_dashes(out, max_dashes=4) if check_dash_count(out) > 4 else out


def _llm_review(pid: str, node: dict, draft: str, plan: dict) -> tuple[dict | None, float]:
    """LLM 层七维度评审;失败不阻塞(advisory)。返回 (评审结果, 本次成本)。"""
    try:
        assembly = build_assembly(pid, node["id"], log=False)
        prompt = _prompt("章节-评审.md", {
            "{{DRAFT}}": draft,
            "{{ASSEMBLED}}": assembled_text(assembly)[:6000],
            "{{PLAN}}": json.dumps(plan, ensure_ascii=False, indent=1),
        })
        r = chat_completion(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": "请输出七维度评审 JSON。"}],
            action="chapter_review", project_id=pid, node_id=node["id"], agent_type="reviewer",
            # 8000:评审走 max 档,思考会先吃掉 2-5K,2500 装不下七维度 JSON
            input_summary=f"评审:{node['title']}", max_tokens_override=8000)
        try:
            parsed = _parse_json_loose(r["content"])
        except (ValueError, json.JSONDecodeError):
            # 解析失败不丢评审:保留原文供人阅读(实测发现的真问题,max 档输出格式不稳)
            parsed = {"raw": r["content"], "parse_error": True}
        # 成本照记(841ebd6 发现的待修:评审调用此前漏出 usage_total)
        return parsed, r["usage"]["cost_total"]
    except Exception as exc:  # S7:评审是 advisory 不阻塞,但失败必须留痕,不许静默 None
        return {"review_error": f"评审调用失败:{exc}"}, 0.0


def _repair_once(pid: str, node: dict, skill: str | None) -> tuple[dict, float]:
    """AI 自修一轮共享实现(需求2:自修同样吃技能);返回 (结果包, 本次成本)。"""
    cs = _open_changeset(node["id"])
    if cs is None:
        raise HTTPException(404, "该章没有打开的变更集")
    view = _changeset_view(cs)
    patch = next((p for p in view["patches"] if p["field"] == "content"), None)
    if patch is None:
        raise HTTPException(404, "变更集缺少正文补丁")
    issues = [v for v in view["validations"] if not v.get("dismissed")]
    if not issues:
        return {"changeset": view, "note": "审计无问题,无需自修", "usage_total": 0.0}, 0.0

    lines = []
    for v in issues:
        tag = "[可自动修复]" if v.get("auto_fixable") else "[需人工确认]"
        lines.append(f"- {tag} {v['dimension']}:{v['message']} → {v.get('suggestion','')}")
    plan = get_chapter_plan(node["id"])
    prompt = _prompt("章节-自修.md", {
        "{{DRAFT}}": patch["after"], "{{ISSUES}}": "\n".join(lines),
        "{{PLAN}}": json.dumps(plan, ensure_ascii=False, indent=1),
        "{{ANTI_AI}}": build_anti_ai_prompt_section(),
    })
    skill_text = skill_section(skill)
    if skill_text:
        prompt += "\n\n" + skill_text
    r = chat_completion(
        [{"role": "system", "content": prompt}, {"role": "user", "content": "输出修复后的完整正文。"}],
        action="chapter_repair", project_id=pid, node_id=node["id"], agent_type="writer",
        # 同草稿:max 档思考 + 完整正文
        input_summary=f"自修:{node['title']}", max_tokens_override=24000)
    repaired = r["content"].strip()
    if check_dash_count(repaired) > 4:
        repaired = cleanup_dashes(repaired, max_dashes=4)
    validations, _ = _code_audit(pid, node, repaired)
    # 自修改了正文,重审计同样要延续人工豁免(与 save_human_edit 同款;豁免键已改不含 evidence)
    _carry_dismissals(validations, view["validations"])
    with tx() as conn:
        conn.execute(
            "UPDATE changesets SET validations=?, updated_at=? WHERE id=?",
            (json.dumps(validations, ensure_ascii=False), _now(), cs["id"]))
        _put_patch(conn, cs["id"], node["id"], repaired, "AI 自修一轮",
                   cs.get("base_revision"), source="ai")
        fresh = dict(conn.execute("SELECT * FROM changesets WHERE id=?", (cs["id"],)).fetchone())
    usage = r["usage"]["cost_total"]
    return ({"changeset": _changeset_view(fresh), "note": None,
             "usage_total": usage, "skill": skill}, usage)
