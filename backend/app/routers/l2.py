"""L2 回写提取(F9):定稿后机器起草真相文件 diff。

移植自 inkflow Observer/Reflector 思路:用定稿正文+现有真相文件,
让 LLM 提取本章新事实(角色状态/资源增减/关系/情绪/信息获知/伏笔埋收/时间线),
产出草稿 diff 进 l2_files 草案区,**人批准才合并官方区**(写入协议)。
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..audit.world_state import L2_TYPES, load_world_state
from ..common import _now, _prompt
from ..settings_store import touch_prompt_append
from ..db import tx
from ..ledger.usage import chat_completion

router = APIRouter(prefix="/api/l2", tags=["l2"])


@router.get("/drafts")
def list_drafts(project_id: str) -> dict:
    with tx() as conn:
        drafts = [dict(r) for r in conn.execute(
            "SELECT id, file_type, content, updated_at FROM l2_files"
            " WHERE project_id=? AND status='draft' ORDER BY file_type", (project_id,)).fetchall()]
        official = {r["file_type"]: r["content"] for r in conn.execute(
            "SELECT file_type, content FROM l2_files WHERE project_id=? AND status='official'",
            (project_id,)).fetchall()}
    for d in drafts:
        d["before"] = official.get(d["file_type"], "")
        try:
            d["content_json"] = json.loads(d["content"])
            d["before_json"] = json.loads(d["before"]) if d["before"] else None
        except (json.JSONDecodeError, TypeError):
            d["content_json"] = None
            d["before_json"] = None
    return {"drafts": drafts}


class DraftIn(BaseModel):
    node_id: str
    text: str


def draft_l2_internal(project_id: str, node_id: str, text: str) -> dict:
    """机器起草真相文件 diff;供端点与定稿流程共用。"""
    ws = load_world_state(project_id)
    # 8000/12000:真相文件与单章正文进 prompt 的截断上限(口径:单次调用 token 预算内)
    current_truth = json.dumps(ws.raw, ensure_ascii=False, indent=1)[:8000]
    prompt = _prompt("L2-回写提取.md", {
        "{{CHAPTER_TEXT}}": text[:12000],
        "{{CURRENT_TRUTH}}": current_truth,
    })
    prompt += touch_prompt_append("l2_rewrite_draft")   # 批次六甲:触点追加
    r = chat_completion(
        [{"role": "system", "content": prompt},
         {"role": "user", "content": "请输出真相文件变更 JSON。"}],
        action="l2_rewrite_draft", project_id=project_id, node_id=node_id, agent_type="observer",
        input_summary="L2回写起草")  # 上限=TOUCHES 登记 6000
    raw = r["content"].strip()
    if raw.startswith("```"):
        first, last = raw.find("\n"), raw.rfind("```")
        if first != -1 and last > first:
            raw = raw[first + 1:last].strip()
    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, f"回写提取输出不是合法 JSON({exc});可重试")

    # 回写校验器(拍板:新角色名/资源必须在正文有依据)
    validator_notes: dict[str, list[str]] = {}

    def _note(ft: str, msg: str) -> None:
        validator_notes.setdefault(ft, []).append(msg)

    characters = changes.get("character_matrix", {}).get("characters", {})
    if isinstance(characters, dict):
        existing = set(ws.characters.keys())
        for name, info in characters.items():
            if name not in existing and isinstance(info, dict):
                status = str(info.get("status", "alive"))
                if status == "alive" and name not in text:
                    _note("character_matrix", f"新角色「{name}」未在正文中出现,疑似幻觉")
    resources = changes.get("resource_ledger", {}).get("entries", {})
    if isinstance(resources, dict):
        for key, info in resources.items():
            if isinstance(info, dict) and str(info.get("status")) in ("lost", "consumed", "destroyed"):
                name = str(info.get("name", key))
                if name and name not in text:
                    _note("resource_ledger", f"资源「{name}」状态变化但正文中未提及该名称")

    now = _now()
    created = []
    with tx() as conn:
        for ft in L2_TYPES:
            if ft not in changes or not isinstance(changes[ft], dict):
                continue
            # 同类型同章旧草案先清掉,避免堆积
            conn.execute(
                "DELETE FROM l2_files WHERE project_id=? AND file_type=? AND status='draft'",
                (project_id, ft))
            did = f"l2d_{uuid.uuid4().hex[:20]}"
            notes = validator_notes.get(ft, [])
            conn.execute(
                "INSERT INTO l2_files(id, project_id, file_type, content, status, updated_at)"
                " VALUES(?,?,?,?, 'draft', ?)",
                (did, project_id, ft,
                 json.dumps({"data": changes[ft], "validator_notes": notes},
                            ensure_ascii=False) if notes else json.dumps(changes[ft], ensure_ascii=False),
                 now))
            created.append(did)
    return {"ok": True, "drafts": created, "count": len(created), "usage": r["usage"]}


@router.post("/draft")
def draft_l2(project_id: str, body: DraftIn) -> dict:
    """端点包装:定稿后调用(工作台/终审页手动触发)。"""
    return draft_l2_internal(project_id, body.node_id, body.text)


@router.post("/draft-async")
def draft_l2_async(project_id: str, body: DraftIn) -> dict:
    """批次二 AI 流升级:L2 起草后台任务化(阶段可查/切页签不丢,成本入任务)。"""
    import threading as _threading
    from .task_runner import ACTIVE_NODES, create_task, finish_task, set_stage
    key = body.node_id
    if ACTIVE_NODES.get(key):
        raise HTTPException(409, "该章已有任务在跑")
    row = create_task(project_id, {"id": body.node_id}, "l2_redraft", None)

    def _run() -> None:
        try:
            set_stage(row["id"], "calling")
            r = draft_l2_internal(project_id, body.node_id, body.text)
            finish_task(row["id"], key, result={"count": r.get("count")},
                        usage_total=(r.get("usage") or {}).get("cost_total"))
        except Exception as exc:
            finish_task(row["id"], key, error=str(exc)[:2000])

    _threading.Thread(target=_run, daemon=True).start()
    return {"task": row}


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: str) -> dict:
    """批准:草案内容合并为官方区(整体替换该类型),草案删除。"""
    with tx() as conn:
        row = conn.execute("SELECT * FROM l2_files WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "草案不存在")
        if row["status"] != "draft":
            raise HTTPException(422, "该行不是草案")
        conn.execute(
            "INSERT INTO l2_files(id, project_id, file_type, content, status, updated_at)"
            " VALUES(?,?,?,?, 'official', ?)"
            " ON CONFLICT(project_id, file_type, status) DO UPDATE SET"
            " content=excluded.content, updated_at=excluded.updated_at",
            (f"l2_{uuid.uuid4().hex[:20]}", row["project_id"], row["file_type"],
             row["content"], _now()))
        conn.execute("DELETE FROM l2_files WHERE id=?", (draft_id,))
    return {"ok": True}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT status FROM l2_files WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "草案不存在")
        if row["status"] != "draft":
            raise HTTPException(422, "该行不是草案")
        conn.execute("DELETE FROM l2_files WHERE id=?", (draft_id,))
    return {"ok": True}


@router.get("/hooks")
def hook_board(project_id: str) -> dict:
    """伏笔池看板(F10):生命周期 + 烂尾告警(>15 章未回收标红)。"""
    ws = load_world_state(project_id)
    cur = 0
    with tx() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM outline_nodes WHERE project_id=? AND kind='chapter'",
            (project_id,)).fetchone()
        cur = row["n"]
    hooks = []
    for f in ws.foreshadowing_pool:
        age = cur - f.planted_chapter
        hooks.append({
            "detail": f.detail, "planted_chapter": f.planted_chapter,
            "status": f.status, "age": age,
            "stale": f.status == "pending" and age >= 15,
        })
    hooks.sort(key=lambda h: (-h["stale"], -h["age"]))
    return {"hooks": hooks, "current_chapter": cur, "stale_threshold": 15}
