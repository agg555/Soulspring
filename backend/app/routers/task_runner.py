"""后台任务机制(S2 拆自 workbench.py,审计 2026-09-01 §2.1)。

锁 + 活线程注册表 + gen_tasks 状态机(set_stage/finish/heal/视图)。
workbench(生成/自修)与 conversations(对话)共同依赖本模块,依赖图从
三角变扇形;函数名去下划线前缀转正为模块公开 API。

注册表键语义(task_key):生成/自修任务按章(node_id);对话任务(kind=chat)
按会话线(chat:{session_id})。注册表仅本进程存活,重启即空——db 里 status='running'
但注册表查无此键的任务由 heal_stale 标记为中断。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from ..common import _now
from ..db import tx

TASK_LOCK = threading.Lock()
ACTIVE_NODES: dict[str, str] = {}   # 任务键 -> task_id(本进程活线程注册表,重启即空)


def task_key(row: dict) -> str:
    """活线程注册表键:生成/自修按章;对话任务(kind=chat)按会话线,node_id 为空串。"""
    if row.get("kind") == "chat":
        return f"chat:{row.get('session_id') or ''}"
    return row.get("node_id") or ""


def steps_for(tid: str) -> list[dict]:
    """任务步骤时间线(批次七③):按序返回环节明细,供任务卡展开。"""
    with tx() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM gen_task_steps WHERE task_id=? ORDER BY seq", (tid,))]


def task_view(row: dict) -> dict:
    out = dict(row)
    if out.get("result"):
        try:
            out["result"] = json.loads(out["result"])
        except json.JSONDecodeError:
            out["result"] = None
    out["steps"] = steps_for(row["id"])   # 批次七③:轮询返回体加厚,步骤随任务走
    return out


def create_task(pid: str, node: dict, kind: str, skill: str | None) -> dict:
    tid = f"task_{uuid.uuid4().hex[:20]}"
    now = _now()
    with tx() as conn:
        conn.execute(
            "INSERT INTO gen_tasks(id, project_id, node_id, kind, skill, stage, status,"
            " created_at, updated_at) VALUES(?,?,?,?,?,'queued','running',?,?)",
            (tid, pid, node["id"], kind, skill, now, now))
        row = dict(conn.execute("SELECT * FROM gen_tasks WHERE id=?", (tid,)).fetchone())
    with TASK_LOCK:
        ACTIVE_NODES[node["id"]] = tid   # 先注册再起线程,读端据此判定重启残留
    return row


def set_stage(tid: str, stage: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE gen_tasks SET stage=?, updated_at=? WHERE id=?",
                     (stage, _now(), tid))


def finish_task(tid: str, key: str, *, error: str | None = None,
                result: dict | None = None, usage_total: float | None = None) -> None:
    """key = task_key 所用注册表键(生成任务=章 id,对话任务=chat:{session_id})。"""
    with tx() as conn:
        conn.execute(
            "UPDATE gen_tasks SET status=?, stage=?, error=?, result=?, usage_total=?,"
            " updated_at=? WHERE id=?",
            ("error" if error else "done", "error" if error else "done",
             error, json.dumps(result, ensure_ascii=False) if result else None,
             usage_total, _now(), tid))
    with TASK_LOCK:
        if ACTIVE_NODES.get(key) == tid:
            ACTIVE_NODES.pop(key, None)


def heal_stale(row: dict) -> dict:
    """db 说 running 但本进程无该线程注册 → 服务重启残留,标记 error。"""
    if row.get("status") == "running" and ACTIVE_NODES.get(task_key(row)) != row["id"]:
        with tx() as conn:
            conn.execute(
                "UPDATE gen_tasks SET status='error', stage='error', error='服务重启,任务中断',"
                " updated_at=? WHERE id=?", (_now(), row["id"]))
            conn.execute(
                "UPDATE gen_task_steps SET status='error', artifact='任务中断(服务重启)',"
                " finished_at=? WHERE task_id=? AND status='running'", (_now(), row["id"]))
        row["status"] = row["stage"] = "error"
        row["error"] = "服务重启,任务中断"
    return row


# ── 步骤明细(批次七③):工具/环节名+参数摘要+状态+起止+中间产物摘要 ──

def _iso_minus_now(iso: str) -> int:
    """started_at(UTC ISO)距今毫秒数;解析失败回 0(计时是展示件,不该炸主流程)。"""
    try:
        t0 = datetime.fromisoformat(iso)
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - t0).total_seconds() * 1000))
    except (ValueError, TypeError):
        return 0


def start_step(tid: str, name: str, tool: str = "", params: str = "") -> str:
    sid = f"step_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM gen_task_steps WHERE task_id=?",
            (tid,)).fetchone()[0]
        conn.execute(
            "INSERT INTO gen_task_steps(id, task_id, seq, name, tool, params, status,"
            " started_at) VALUES(?,?,?,?,?,?,'running',?)",
            (sid, tid, seq, name, tool, params, _now()))
    return sid


def finish_step(step_id: str, *, status: str = "done", artifact: str = "",
                tool: str = "") -> None:
    with tx() as conn:
        row = conn.execute(
            "SELECT started_at FROM gen_task_steps WHERE id=?", (step_id,)).fetchone()
        if row is None:
            return
        conn.execute(
            "UPDATE gen_task_steps SET status=?, artifact=?,"
            + ("tool=?," if tool else "") +
            " finished_at=?, duration_ms=?"
            " WHERE id=?",
            (status, artifact, *([tool] if tool else []),
             _now(), _iso_minus_now(row["started_at"]), step_id))


def annotate_step(tid: str, name: str, *, tool: str = "", artifact: str = "") -> None:
    """回填同名最近一步的工具/产物(步骤结束时点在调用方手里,早开的一步事后补记)。"""
    with tx() as conn:
        row = conn.execute(
            "SELECT id FROM gen_task_steps WHERE task_id=? AND name=?"
            " ORDER BY seq DESC LIMIT 1", (tid, name)).fetchone()
        if row is None:
            return
        sets, args = [], []
        if tool:
            sets.append("tool=?"); args.append(tool)
        if artifact:
            sets.append("artifact=?"); args.append(artifact)
        if not sets:
            return
        args.append(row["id"])
        conn.execute(f"UPDATE gen_task_steps SET {', '.join(sets)} WHERE id=?", args)


class StepRecorder:
    """任务内顺序步骤:begin 关闭上一步并开新步;finish_current/annotate 收尾补记。

    供 workbench 管道的 progress 回调复用——阶段推进即步骤推进,零额外埋点。
    """

    def __init__(self, tid: str) -> None:
        self.tid = tid
        self.current: str | None = None

    def begin(self, name: str, tool: str = "", params: str = "") -> None:
        self.finish_current()
        self.current = start_step(self.tid, name, tool, params)

    def finish_current(self, *, status: str = "done", artifact: str = "",
                       tool: str = "") -> None:
        if self.current:
            finish_step(self.current, status=status, artifact=artifact, tool=tool)
            self.current = None

    def annotate(self, name: str, *, tool: str = "", artifact: str = "") -> None:
        """按名回填已开步骤的工具/产物(plan 在 draft 开始时才拿到产物)。"""
        annotate_step(self.tid, name, tool=tool, artifact=artifact)

    def close(self, *, status: str = "done", artifact: str = "") -> None:
        """任务收尾兜底:不许步骤挂着 running 出场。"""
        self.finish_current(status=status, artifact=artifact)
