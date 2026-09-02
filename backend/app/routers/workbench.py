"""写章工作台 API(M3 核心):装配预览 → 计划卡 → 草稿 → 双层审计 → 人改 → 合入。

设计决议(执行计划书 §4.1):
- 变更集按 chevoink 完整契约:patches 逐条 + validations 审计挂钩 + 乐观锁;
- repair 灵活模式:审计不过默认人修,提供"AI 自修一轮"按钮(设置可关);
- 字数规整器可关;评审报告随草稿生成(可在设置关闭省 token);
- 代码层审计 critical 不清零 → 不允许应用合入(检查协议闸门)。
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..assembly import build_assembly, get_chapter_plan, save_chapter_plan
from ..common import _now
from ..db import tx
from ..llm.atomic_io import write_text_atomic
from ..settings_store import get_settings, resolve_skill
from .changeset_ops import (
    _carry_dismissals,
    _changeset_view,
    _code_audit,
    _get_node,
    _open_changeset,
    _put_patch,
)
from .generation import _generate_draft_text, _llm_review, _repair_once
from .task_runner import create_task, finish_task, heal_stale, set_stage, task_view

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


def _transition(conn, node: dict, to_status: str) -> None:
    """章节点状态推进(带时间戳日志);与大纲树状态机共用同一张日志表。"""
    from .outline import TRANSITIONS
    if node["status"] == to_status:
        return
    if to_status not in TRANSITIONS.get(node["status"], set()):
        return  # 非法迁移静默跳过:工作台动作不应被状态机卡死,由大纲树页严格把关
    now = _now()
    conn.execute(
        "UPDATE outline_nodes SET status=?, status_changed_at=?, updated_at=? WHERE id=?",
        (to_status, now, now, node["id"]))
    conn.execute(
        "INSERT INTO l3_status_log(id, node_id, from_status, to_status, changed_at)"
        " VALUES(?,?,?,?,?)",
        (f"stat_{uuid.uuid4().hex[:20]}", node["id"], node["status"], to_status, now))


def _replace_changeset(pid: str, node: dict, draft: str, plan: dict,
                       validations: list, review: dict | None, cs: dict | None) -> dict:
    """创建或替换(重 roll)节点当前打开的变更集,并重新审计入库。"""
    with tx() as conn:
        l4row = conn.execute(
            "SELECT content, revision FROM l4_texts WHERE node_id=?", (node["id"],)).fetchone()
        base_revision = l4row["revision"] if l4row else 0
        now = _now()
        if cs is None:
            cs_id = f"cs_{uuid.uuid4().hex[:20]}"
            conn.execute(
                "INSERT INTO changesets(id, project_id, node_id, kind, status, payload,"
                " base_revision, validations, task_spec, review, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (cs_id, pid, node["id"], "draft", "draft", "{}", base_revision,
                 json.dumps(validations, ensure_ascii=False),
                 json.dumps(plan, ensure_ascii=False),
                 json.dumps(review, ensure_ascii=False) if review else None, now, now))
        else:
            cs_id = cs["id"]
            conn.execute(
                "UPDATE changesets SET status='draft', base_revision=?, validations=?,"
                " task_spec=?, review=?, updated_at=? WHERE id=?",
                (base_revision, json.dumps(validations, ensure_ascii=False),
                 json.dumps(plan, ensure_ascii=False),
                 json.dumps(review, ensure_ascii=False) if review else None, now, cs_id))
        _put_patch(conn, cs_id, node["id"], draft, "AI 草稿", base_revision, source="ai")
        if node["status"] == "unwritten":
            _transition(conn, node, "draft")  # 生成草稿 = 状态机 未写→草稿
        fresh = dict(conn.execute("SELECT * FROM changesets WHERE id=?", (cs_id,)).fetchone())
    return _changeset_view(fresh)


# ── 路由 ──

@router.get("/{nid}/preview")
def preview(nid: str, project_id: str) -> dict:
    node = _get_node(project_id, nid)
    assembly = build_assembly(project_id, nid, log=False)
    with tx() as conn:
        l4 = conn.execute("SELECT content, revision FROM l4_texts WHERE node_id=?",
                          (nid,)).fetchone()
    skills_cfg = get_settings()["skills"]
    return {
        "node": node,
        "plan": get_chapter_plan(nid),
        "assembly": assembly,
        "current_text": l4["content"] if l4 else "",
        "revision": l4["revision"] if l4 else 0,
        "changeset": (_open_changeset(nid) and _changeset_view(_open_changeset(nid))) or None,
        # 技能三档(需求3):前端下拉初值 = override ?? global;override 为 null 表示"跟随全局"
        "skill_effective": resolve_skill(project_id),
        "skill_override": (skills_cfg.get("book_overrides") or {}).get(project_id),
        "skill_global": skills_cfg.get("global_default") or "",
        # 进行中任务(需求1):切走再切回时前端据此续显进度
        "running_task": _running_task(nid),
    }


class PlanIn(BaseModel):
    plan: dict


@router.put("/{nid}/plan")
def put_plan(nid: str, body: PlanIn, project_id: str) -> dict:
    _get_node(project_id, nid)
    save_chapter_plan(nid, body.plan)
    return {"ok": True, "plan": body.plan}


class GenerateIn(BaseModel):
    # None = 按三档解析(手选未动>单本书>全局);"" = 明确不启用;"技能名" = 手选
    skill: str | None = None


def _running_task(nid: str) -> dict | None:
    with tx() as conn:
        row = conn.execute(
            "SELECT * FROM gen_tasks WHERE node_id=? AND status='running'"
            " ORDER BY created_at DESC LIMIT 1", (nid,)).fetchone()
    return task_view(heal_stale(dict(row))) if row else None


def _run_generation(tid: str, pid: str, node: dict, skill: str | None, kind: str) -> None:
    """后台线程:跑完整管道,阶段写 gen_tasks.stage;异常兜底落 error,不让线程裸死。"""
    try:
        def progress(stage: str) -> None:
            set_stage(tid, stage)

        if kind == "draft":
            cs = _open_changeset(node["id"])
            draft, plan, calls = _generate_draft_text(
                pid, node, force_new_plan=False, skill=skill, progress=progress)
            progress("audit")
            validations, _ = _code_audit(pid, node, draft)
            review = None
            review_err = None
            review_cost = 0.0
            if get_settings()["workbench"].get("llm_review", True):
                progress("review")
                review, review_cost = _llm_review(pid, node, draft, plan)
                if isinstance(review, dict) and review.get("review_error"):
                    # S7:评审失败可见——异常串经任务 note 弹出,不写进 changeset.review
                    review_err = review.pop("review_error")
                    if not review:
                        review = None
            view = _replace_changeset(pid, node, draft, plan, validations, review, cs)
            view["skill"] = skill
            usage = round(sum(c["usage"]["cost_total"] for c in calls) + review_cost, 6)
            result = {"changeset": view, "note": review_err, "usage_total": usage}
        else:
            progress("repair")
            result, usage = _repair_once(pid, node, skill)
        finish_task(tid, node["id"], result=result, usage_total=usage)
    except Exception as exc:  # noqa: BLE001 任务记录是唯一出口
        finish_task(tid, node["id"], error=str(exc))


@router.post("/{nid}/draft")
def generate_draft(nid: str, project_id: str, body: GenerateIn | None = None) -> dict:
    """后台生成:立即返回任务号;进度 GET /api/workbench/tasks/{tid}。

    完整管道:计划卡(缺则生成)→ 草稿 → 规整 → 审计 → (评审)→ 变更集。
    同章已有运行中任务 → 409(防重复点击重复计费)。
    """
    node = _get_node(project_id, nid)
    running = _running_task(nid)
    if running:
        raise HTTPException(409, f"该章已有生成任务在跑(阶段:{running['stage']}),请等它完成,勿重复生成")
    skill = resolve_skill(project_id, body.skill if body else None)
    row = create_task(project_id, node, "draft", skill or None)
    threading.Thread(target=_run_generation,
                     args=(row["id"], project_id, node, skill or None, "draft"),
                     daemon=True).start()
    return {"ok": True, "task": task_view(row)}


class DraftIn(BaseModel):
    text: str


@router.put("/{nid}/draft")
def save_human_edit(nid: str, project_id: str, body: DraftIn) -> dict:
    """人改保存:更新 patch.after 并重跑零 token 审计(人改路径,拍板决议 2)。"""
    node = _get_node(project_id, nid)
    cs = _open_changeset(nid)
    if cs is None:
        raise HTTPException(404, "该章没有打开的变更集")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "正文不能为空")
    validations, _ = _code_audit(project_id, node, text)
    _carry_dismissals(validations, _open_changeset(nid) and _changeset_view(_open_changeset(nid))["validations"] or [])
    with tx() as conn:
        conn.execute(
            "UPDATE changesets SET status='draft', validations=?, updated_at=? WHERE id=?",
            (json.dumps(validations, ensure_ascii=False), _now(), cs["id"]))
        _put_patch(conn, cs["id"], nid, text, "人改", cs.get("base_revision"), source="human")
        if node["status"] == "draft":
            _transition(conn, node, "human_editing")  # 开始人改 = 状态机 草稿→人改中
        fresh = dict(conn.execute("SELECT * FROM changesets WHERE id=?", (cs["id"],)).fetchone())
    return _changeset_view(fresh)


@router.post("/{nid}/repair")
def repair(nid: str, project_id: str, body: GenerateIn | None = None) -> dict:
    """AI 自修一轮(后台任务):按问题清单定向修,修完重审计并延续豁免。"""
    node = _get_node(project_id, nid)
    running = _running_task(nid)
    if running:
        raise HTTPException(409, "该章已有任务在跑,勿重复触发")
    skill = resolve_skill(project_id, body.skill if body else None)
    row = create_task(project_id, node, "repair", skill or None)
    threading.Thread(target=_run_generation,
                     args=(row["id"], project_id, node, skill or None, "repair"),
                     daemon=True).start()
    return {"ok": True, "task": task_view(row)}


@router.get("/tasks/active")
def active_tasks() -> dict:
    """全局徽标数据源(需求1):跨书的运行中任务(生成/对话),带书名/章名/阶段。"""
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT t.*, n.title AS node_title, p.name AS project_name FROM gen_tasks t"
            " LEFT JOIN outline_nodes n ON n.id = t.node_id"
            " LEFT JOIN projects p ON p.id = t.project_id"
            " WHERE t.status = 'running' ORDER BY t.created_at")]
    return {"tasks": [task_view(heal_stale(r)) for r in rows]}


@router.get("/tasks/{tid}")
def get_task(tid: str) -> dict:
    """任务状态查询:进行中/已结束同源返回,前端轮询与回显共用。"""
    with tx() as conn:
        row = conn.execute("SELECT * FROM gen_tasks WHERE id=?", (tid,)).fetchone()
    if row is None:
        raise HTTPException(404, "任务不存在")
    return {"task": task_view(heal_stale(dict(row)))}


class DismissIn(BaseModel):
    index: int
    note: str = ""


@router.post("/{nid}/validations/dismiss")
def dismiss_validation(nid: str, project_id: str, body: DismissIn) -> dict:
    """人工豁免:人裁决某条审计问题为误报(带备注,重审计自动延续)。"""
    cs = _open_changeset(nid)
    if cs is None:
        raise HTTPException(404, "该章没有打开的变更集")
    view = _changeset_view(cs)
    if body.index < 0 or body.index >= len(view["validations"]):
        raise HTTPException(422, "问题序号无效")
    v = view["validations"][body.index]
    v["dismissed"] = True
    v["dismiss_note"] = body.note.strip() or "人工确认为误报"
    with tx() as conn:
        conn.execute("UPDATE changesets SET validations=?, updated_at=? WHERE id=?",
                     (json.dumps(view["validations"], ensure_ascii=False), _now(), cs["id"]))
    return {"ok": True, "validations": view["validations"]}


# ── 版本历史(C5,执行书 2026-08-31):任选两版对比 + 回滚 ──

@router.get("/{nid}/patch-history")
def patch_history(nid: str, project_id: str) -> dict:
    """当前打开变更集的全部补丁版本(追加式留痕,重 roll/人改/自修各占一版)。"""
    cs = _open_changeset(nid)
    if cs is None:
        raise HTTPException(404, "该章没有打开的变更集")
    view = _changeset_view(cs)
    return {"changeset_id": cs["id"], "patches": view["patch_history"]}


class RollbackIn(BaseModel):
    patch_id: str


@router.post("/{nid}/patch-rollback")
def patch_rollback(nid: str, project_id: str, body: RollbackIn) -> dict:
    """回滚到指定历史版本:以该版本文本为 after 追加一个新版本(版本链完整,不删历史)。

    重审计并延续人工豁免,与人改保存同款;回滚本身也是一版,可再滚回来。
    """
    node = _get_node(project_id, nid)
    cs = _open_changeset(nid)
    if cs is None:
        raise HTTPException(404, "该章没有打开的变更集")
    view = _changeset_view(cs)
    target = next((p for p in view["patch_history"] if p["id"] == body.patch_id), None)
    if target is None:
        raise HTTPException(404, "历史版本不存在")
    validations, _ = _code_audit(project_id, node, target["after"])
    _carry_dismissals(validations, view["validations"])
    with tx() as conn:
        conn.execute(
            "UPDATE changesets SET status='draft', validations=?, updated_at=? WHERE id=?",
            (json.dumps(validations, ensure_ascii=False), _now(), cs["id"]))
        _put_patch(conn, cs["id"], nid, target["after"],
                   f"回滚到 v{target['version']}({target['reason']})", cs.get("base_revision"))
        fresh = dict(conn.execute("SELECT * FROM changesets WHERE id=?", (cs["id"],)).fetchone())
    return _changeset_view(fresh)


@router.post("/{nid}/apply")
def apply_changeset_internal(nid: str, project_id: str) -> dict:
    """合入正式正文(l4_texts + .md 镜像);闸门:代码层审计无未豁免 critical。
    供本路由 apply 端点与审稿对话台"通过→定稿"共用。"""
    cs = _open_changeset(nid)
    if cs is None:
        raise HTTPException(404, "该章没有打开的变更集")
    view = _changeset_view(cs)
    critical = [v for v in view["validations"] if v["status"] == "failed" and not v.get("dismissed")]
    if critical:
        raise HTTPException(409, f"代码层审计存在 {len(critical)} 个 critical 问题(未被人工豁免),不允许合入")
    patch = next((p for p in view["patches"] if p["field"] == "content"), None)
    if patch is None:
        raise HTTPException(404, "变更集缺少正文补丁")
    now = _now()
    with tx() as conn:
        row = conn.execute("SELECT revision FROM l4_texts WHERE node_id=?", (nid,)).fetchone()
        if row:
            conn.execute(
                "UPDATE l4_texts SET content=?, revision=revision+1, updated_at=? WHERE node_id=?",
                (patch["after"], now, nid))
            new_revision = row["revision"] + 1
        else:
            conn.execute(
                "INSERT INTO l4_texts(node_id, content, md_path, updated_at) VALUES(?,?,?,?)",
                (nid, patch["after"], None, now))
            new_revision = 1
        conn.execute(
            "UPDATE changesets SET status='applied', updated_at=?, decided_at=? WHERE id=?",
            (now, now, cs["id"]))
        conn.execute(
            "UPDATE changeset_patches SET applied_revision=?, selected=1 WHERE changeset_id=?",
            (new_revision, cs["id"]))
    md_dir = Path(__file__).resolve().parents[3] / "data" / "chapters" / project_id
    md_path = str(md_dir / f"{nid}.md")
    write_text_atomic(md_path, patch["after"])
    with tx() as conn:
        conn.execute("UPDATE l4_texts SET md_path=? WHERE node_id=?", (md_path, nid))
    return {"ok": True, "revision": new_revision, "md_path": md_path, "text": patch["after"]}
