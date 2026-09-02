"""审稿对话台(F8)+ 终审与定稿(F8↔L3)+ 朱雀登记(S5 五件套)。

- 对话部分(A3,2026-08-31)迁入 routers/conversations.py 统一会话制
  (多线会话 + 发送任务化 + 建议块采纳),本文件保留:技能列表 / 通过打回 / 朱雀登记;
- 通过:待终审→定稿,自动合入变更集(l4+.md 镜像),并触发 L2 回写起草(人批准才入账);
- 打回:待终审→人改中,备注入状态日志。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now, _parse_frontmatter
from ..db import tx
from .workbench import apply_changeset_internal

router = APIRouter(prefix="/api/review", tags=["review"])

SKILLS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "技能"


@router.get("/skills")
def list_skills() -> dict:
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if d.is_dir() and f.exists():
            meta, _ = _parse_frontmatter(f.read_text(encoding="utf-8"))
            skills.append({"key": d.name, "name": meta.get("name", d.name),
                           "description": meta.get("description", "")})
    return {"skills": skills}


@router.get("/skills/{key}")
def skill_detail(key: str) -> dict:
    f = SKILLS_DIR / key / "SKILL.md"
    if not f.exists():
        raise HTTPException(404, "技能不存在")
    meta, body = _parse_frontmatter(f.read_text(encoding="utf-8"))
    return {"key": key, "name": meta.get("name", key), "description": meta.get("description", ""),
            "body": body}


# ── 终审队列:通过 / 打回 ──

@router.get("/queue")
def final_review_queue(project_id: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, title, status, status_changed_at FROM outline_nodes"
            " WHERE project_id=? AND kind='chapter' AND status IN ('final_review','human_editing')"
            " ORDER BY status, sort_order", (project_id,)).fetchall()]
    return {"queue": rows}


def _set_status(conn, node: dict, to_status: str, note: str | None = None) -> None:
    now = _now()
    conn.execute(
        "UPDATE outline_nodes SET status=?, status_changed_at=?, updated_at=? WHERE id=?",
        (to_status, now, now, node["id"]))
    conn.execute(
        "INSERT INTO l3_status_log(id, node_id, from_status, to_status, changed_at, note)"
        " VALUES(?,?,?,?,?,?)",
        (f"stat_{uuid.uuid4().hex[:20]}", node["id"], node["status"], to_status, now, note))


@router.post("/{nid}/approve")
def approve_final(nid: str, project_id: str) -> dict:
    """终审通过:→定稿;合入变更集;触发 L2 回写起草(草案区待批)。"""
    with tx() as conn:
        node = dict(conn.execute(
            "SELECT * FROM outline_nodes WHERE id=? AND project_id=?", (nid, project_id)).fetchone())
        if node is None:
            raise HTTPException(404, "章节点不存在")
        if node["status"] != "final_review":
            raise HTTPException(409, f"当前状态 {node['status']},只有待终审可以定稿")
    applied = apply_changeset_internal(nid, project_id)
    with tx() as conn:
        fresh = dict(conn.execute("SELECT * FROM outline_nodes WHERE id=?", (nid,)).fetchone())
        _set_status(conn, fresh, "finalized", note="终审通过,定稿")
    text = applied.pop("text")
    # 触发 L2 回写起草;失败不阻塞定稿(可手动重试)
    rewrite = None
    try:
        from .l2 import draft_l2_internal
        rewrite = draft_l2_internal(project_id, nid, text)
    except Exception as exc:
        rewrite = {"error": str(exc)[:200]}
    return {"ok": True, "applied": applied, "status": "finalized", "l2_rewrite": rewrite}


class RejectIn(BaseModel):
    note: str = ""


@router.post("/{nid}/reject")
def reject_final(nid: str, project_id: str, body: RejectIn) -> dict:
    """打回:待终审→人改中,备注留痕。"""
    with tx() as conn:
        node = dict(conn.execute(
            "SELECT * FROM outline_nodes WHERE id=? AND project_id=?", (nid, project_id)).fetchone())
        if node is None:
            raise HTTPException(404, "章节点不存在")
        if node["status"] != "final_review":
            raise HTTPException(409, f"当前状态 {node['status']},只有待终审可以打回")
        _set_status(conn, node, "human_editing", note=body.note or "终审打回")
    return {"ok": True, "status": "human_editing"}


# ── 朱雀登记 ──

class ZhuqueIn(BaseModel):
    project_id: str
    node_id: str | None = None
    verdict: str                 # 人工 / 疑似 / 红段
    human_ratio: float | None = None
    suspect_ratio: float | None = None
    red_count: int | None = None
    note: str = ""
    # 段位位置(拍板:比截图更适合 AI 分析对比)——每行一条"段落号/摘录"
    red_segments: list[str] = []
    yellow_segments: list[str] = []
    green_segments: list[str] = []


@router.post("/zhuque")
def zhuque_log_row(body: ZhuqueIn) -> dict:
    if body.verdict not in ("人工", "疑似", "红段"):
        raise HTTPException(422, "verdict 只能是 人工/疑似/红段")
    segments = {"red": body.red_segments, "yellow": body.yellow_segments,
                "green": body.green_segments}
    with tx() as conn:
        conn.execute(
            "INSERT INTO zhuque_log(id, project_id, node_id, verdict, human_ratio,"
            " suspect_ratio, red_count, note, segments, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (f"zq_{uuid.uuid4().hex[:20]}", body.project_id, body.node_id, body.verdict,
             body.human_ratio, body.suspect_ratio, body.red_count, body.note,
             json.dumps(segments, ensure_ascii=False), _now()))
    return {"ok": True}


@router.get("/zhuque")
def zhuque_rows(project_id: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT verdict, human_ratio, suspect_ratio, red_count, note, segments, created_at"
            " FROM zhuque_log WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
            (project_id,)).fetchall()]
        for r in rows:
            try:
                r["segments"] = json.loads(r.get("segments") or "{}")
            except (json.JSONDecodeError, TypeError):
                r["segments"] = {}
    # 每周复测提醒:最近一次登记超过 7 天(或没有)且今天是周一 → 提醒
    now = datetime.now(timezone.utc)
    last = rows[0]["created_at"] if rows else None
    stale = (last is None or (now - datetime.fromisoformat(last)) > timedelta(days=7))
    remind = stale and now.weekday() == 0
    return {"rows": rows, "weekly_reminder": remind}
