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

from ..common import _now
from ..db import tx

TASK_LOCK = threading.Lock()
ACTIVE_NODES: dict[str, str] = {}   # 任务键 -> task_id(本进程活线程注册表,重启即空)


def task_key(row: dict) -> str:
    """活线程注册表键:生成/自修按章;对话任务(kind=chat)按会话线,node_id 为空串。"""
    if row.get("kind") == "chat":
        return f"chat:{row.get('session_id') or ''}"
    return row.get("node_id") or ""


def task_view(row: dict) -> dict:
    out = dict(row)
    if out.get("result"):
        try:
            out["result"] = json.loads(out["result"])
        except json.JSONDecodeError:
            out["result"] = None
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
        row["status"] = row["stage"] = "error"
        row["error"] = "服务重启,任务中断"
    return row
