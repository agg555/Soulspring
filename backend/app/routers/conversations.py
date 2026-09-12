"""统一对话组件后端(A1/A2/A3,执行书 2026-08-31)。

- A3 多线会话:conversation_sessions 每节点可开多条命名对话线,消息挂 session_id;
- A4 发送即任务化(拍板:不做流式):复用 gen_tasks(kind='chat'),同线 running 即 409,
  轮询 /api/workbench/tasks/{tid} 与生成任务同款,live/replay 同源;
- A1 建议块:模型按 JSON 协议回 {reply, suggestions[]},解析失败降级纯文本标 parse_error
  (原文保留);采纳走两档:outline_field 轻档(人确认 diff 后写回节点字段+留痕)、
  chapter_text 重档(追加 patch 进该章变更集,走 AI 自修同管道,人改工作区再合入);
- A2 @引用:attachments 把章/角色/条目/伏笔内容拼进 system;默认上下文 = 面板选中节点
  (review 线自动附加章节正文,由 owner_id 决定)。

大文件拆分批(2026-09-10,纯移动零行为变化):回包解析器在 conv_parse.py;
system 组装链(REPLY_PROTOCOL/PRESET_PROMPTS/OWNER_ACTIONS/AGENT_TYPES/_context_*
/_system_parts/MessageIn)在 conv_context.py——本文件只留会话 CRUD、发送即任务化、
压缩与 @引用清单端点;旧导入路径经下方 re-export 保测试零改动。
"""
from __future__ import annotations

import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..audit.world_state import load_world_state
from ..common import _now
from ..db import tx
from ..ledger.usage import chat_completion
from ..settings_store import get_settings
from .conv_context import (  # noqa: F401  纯移动 re-export(conv_parse 先例):MessageIn/
    AGENT_TYPES,            # _system_parts 自用,REPLY_PROTOCOL 等保测试导入路径
    OWNER_ACTIONS,
    REPLY_PROTOCOL,
    VALID_OWNER_TYPES,
    MessageIn,
    _system_parts,
)
from .task_runner import (
    ACTIVE_NODES,
    TASK_LOCK,
    finish_task,
    heal_stale,
    set_stage,
    task_view,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

@router.delete("/{sid}")
def delete_session(sid: str) -> dict:
    """删除对话线及其全部消息(体感 2026-09-06);进行中的任务标错防悬挂。"""
    with tx() as conn:
        if conn.execute("SELECT 1 FROM conversation_sessions WHERE id=?", (sid,)).fetchone() is None:
            raise HTTPException(404, "会话不存在")
        conn.execute("DELETE FROM review_messages WHERE session_id=?", (sid,))
        conn.execute("UPDATE gen_tasks SET status='error', error='会话已删除', updated_at=?"
                     " WHERE kind='chat' AND session_id=? AND status='running'", (_now(), sid))
        conn.execute("DELETE FROM conversation_sessions WHERE id=?", (sid,))
    return {"ok": True}


# ── 会话 CRUD ──

@router.get("")
def list_sessions(project_id: str = "", owner_type: str = "", owner_id: str = "") -> dict:
    # message_count / last_message_at 是本 SELECT 的计算视图字段,不是
    # conversation_sessions 库列——只能在查询里用,勿在 WHERE/UPDATE 引用(审计 E区注)。
    # 可选过滤全静态参数化:入参非空才参与匹配(? = '' 即不过滤),零拼接,结果行与旧按需拼 AND 一致。
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT s.*,"
            " (SELECT COUNT(*) FROM review_messages m WHERE m.session_id = s.id) AS message_count,"
            " (SELECT MAX(m.created_at) FROM review_messages m WHERE m.session_id = s.id)"
            "   AS last_message_at"
            " FROM conversation_sessions s"
            " WHERE (? = '' OR COALESCE(s.project_id,'') = ?)"
            " AND (? = '' OR s.owner_type = ?)"
            " AND (? = '' OR s.owner_id = ?)"
            " ORDER BY s.created_at",
            (project_id, project_id, owner_type, owner_type, owner_id, owner_id)).fetchall()]
    return {"sessions": rows}


class SessionIn(BaseModel):
    project_id: str | None = None
    owner_type: str
    owner_id: str = ""
    name: str


@router.post("", status_code=201)
def create_session(body: SessionIn) -> dict:
    if body.owner_type not in VALID_OWNER_TYPES:
        raise HTTPException(422, f"未知会话归属类型: {body.owner_type}")
    if not body.name.strip():
        raise HTTPException(422, "会话名不能为空")
    sid = f"conv_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        conn.execute(
            "INSERT INTO conversation_sessions(id, project_id, owner_type, owner_id, name,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (sid, body.project_id, body.owner_type, body.owner_id, body.name.strip(), _now()))
        row = dict(conn.execute("SELECT * FROM conversation_sessions WHERE id=?", (sid,)).fetchone())
    # 与 list_sessions 的视图字段对齐(前端新建后立即渲染计数)
    row["message_count"] = 0
    row["last_message_at"] = None
    return {"session": row}


def _get_session(sid: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM conversation_sessions WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, "会话不存在")
    return dict(row)


@router.get("/{sid}/messages")
def get_messages(sid: str) -> dict:
    _get_session(sid)
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, role, content, meta, created_at FROM review_messages"
            " WHERE session_id=? ORDER BY created_at, rowid", (sid,)).fetchall()]
    for r in rows:
        try:
            r["meta"] = json.loads(r["meta"]) if r["meta"] else None
        except json.JSONDecodeError:
            r["meta"] = None
    return {"messages": rows}


# ── 发送即任务化(A4):同线 running 即 409,完成回填消息 ──

@router.post("/{sid}/messages")
def send_message(sid: str, body: MessageIn) -> dict:
    text = body.message.strip()
    if not text:
        raise HTTPException(422, "消息不能为空")
    session = _get_session(sid)
    with tx() as conn:
        row = conn.execute(
            "SELECT * FROM gen_tasks WHERE session_id=? AND kind='chat' AND status='running'"
            " ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
    if row:
        task_view(heal_stale(dict(row)))
        raise HTTPException(409, "该会话已有消息在生成中,请等它完成")

    tid = f"task_{uuid.uuid4().hex[:20]}"
    now = _now()
    with tx() as conn:
        conn.execute(
            "INSERT INTO gen_tasks(id, project_id, node_id, kind, skill, session_id, stage,"
            " status, created_at, updated_at) VALUES(?,?,?,'chat',?,?,'queued','running',?,?)",
            # 测试对话线无归属书(project_id NULL),gen_tasks 该列 NOT NULL → 落空串
            (tid, session["project_id"] or "", "", body.skill, sid, now, now))
        task_row = dict(conn.execute("SELECT * FROM gen_tasks WHERE id=?", (tid,)).fetchone())
    key = f"chat:{sid}"
    with TASK_LOCK:
        ACTIVE_NODES[key] = tid   # 先注册再起线程,读端据此判定重启残留
    threading.Thread(target=_run_chat_turn, args=(tid, sid, body), daemon=True).start()
    return {"ok": True, "task": task_view(task_row)}


COMPACT_KEEP = 16   # ⑤:压缩后仍装配的最近原文条数(执行书拍板 12/16 取 16 稳)


def _history(sid: str) -> list[dict]:
    """⑤甲+案:历史**全量**装配——修旧实现两错(只取最旧 40 条的失忆 bug + 截断
    打断 DeepSeek 前缀缓存);压缩过的线由 _assembly_history 裁到最近段。"""
    with tx() as conn:
        rows = conn.execute(
            "SELECT role, content FROM review_messages WHERE session_id=?"
            " ORDER BY created_at, rowid", (sid,)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _assembly_history(session: dict) -> list[dict]:
    """⑤:装配历史 = 无摘要→全量;有前情提要→最近 COMPACT_KEEP 条(摘要兜底)。"""
    hist = _history(session["id"])
    if (session.get("digest") or "").strip():
        return hist[-COMPACT_KEEP:]
    return hist


def _compact_session(sid: str, keep: int = COMPACT_KEEP) -> dict:
    """纯算法压缩(零 LLM):最近 keep 条原文保留,更早轮次拼成"前情提要"存会话
    digest(system 常驻);原始消息全留库不删,再压缩=摘要上追加增量段。"""
    with tx() as conn:
        sess = conn.execute(
            "SELECT digest FROM conversation_sessions WHERE id=?", (sid,)).fetchone()
        if sess is None:
            raise HTTPException(404, "会话不存在")
        rows = conn.execute(
            "SELECT role, content FROM review_messages WHERE session_id=?"
            " ORDER BY created_at, rowid", (sid,)).fetchall()
        older = rows[:-keep] if len(rows) > keep else []
        if not older:
            return {"compacted": 0, "digest_chars": len(sess["digest"] or "")}
        lines = []
        for r in older[-30:]:   # 摘要只拼最近 30 条被压缩轮,防段无限膨胀
            who = "我" if r["role"] == "user" else "AI"
            text = " ".join((r["content"] or "").split())
            lines.append(f"- {who}: {text[:80]}{'…' if len(text) > 80 else ''}")
        block = "【前情提要(纯算法拼接,原文仍在库,可随时再压缩)】\n" + "\n".join(lines)
        base = (sess["digest"] or "").strip()
        merged = ((base + "\n" + block).strip() if base else block)[:4000]
        conn.execute(
            "UPDATE conversation_sessions SET digest=? WHERE id=?", (merged, sid))
        return {"compacted": len(older), "digest_chars": len(merged)}


# 解析器已抽至 conv_parse.py(2026-09-10 大工程②去繁化简,纯移动零行为变化);
# 旧名 _parse_reply 保留供本模块调用点与测试导入。
from .conv_parse import parse_reply as _parse_reply  # noqa: E402


def _run_chat_turn(tid: str, sid: str, body: MessageIn) -> None:
    """后台线程:组装上下文 → 调模型 → 解析建议协议 → 消息落库 → 任务收尾。"""
    key = f"chat:{sid}"
    try:
        set_stage(tid, "context")
        session = _get_session(sid)
        # ⑤自动压缩(设置 ui.auto_compact,默认关):无摘要且超 40 条→先拼前情提要
        if (get_settings().get("ui", {}).get("auto_compact")
                and not (session.get("digest") or "").strip()
                and len(_history(sid)) > 40):
            _compact_session(sid)
            session = _get_session(sid)
            set_stage(tid, "context")   # 压缩后刷新会话(带 digest)
        messages = [
            {"role": "system", "content": "\n\n".join(_system_parts(session, body))},
            *_assembly_history(session),
            {"role": "user", "content": body.message.strip()},
        ]
        set_stage(tid, "calling")
        action = OWNER_ACTIONS.get(session["owner_type"], "chat_test")
        r = chat_completion(
            messages, action=action, project_id=session["project_id"],
            agent_type=AGENT_TYPES.get(session["owner_type"], "chat"),
            input_summary=body.message[:200], temperature_override=body.temperature,
            # 上限走 TOUCHES 登记默认 8000(批次六甲收编;M6 实测:对话回包含思考+JSON 协议)
            thinking_override=body.thinking)
        set_stage(tid, "parsing")
        reply, suggestions, parse_error = _parse_reply(r["content"])
        # 空回包可读兜底(2026-09-09 实锤:思考吃满输出上限时 content 空字符串,
        # 前端只剩提示行看不见任何解释);原文非空时维持原样降级,不篡改。
        if not r["content"].strip():
            reply = ("(模型这次只思考没输出正文——通常是思考吃满了输出上限。"
                     "可在上方把「思考」切到「关」后重发;费用已按实际 token 计。)")
            suggestions = []
            parse_error = True
        # 下限告警线(2026-09-09):低于下限随 meta 透传,前端黄条提示;不拦截。
        limit_warning = r.get("limit_warning")
        now = _now()
        with tx() as conn:
            conn.execute(
                "INSERT INTO review_messages(id, project_id, session_id, node_id, role,"
                " content, meta, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"rev_{uuid.uuid4().hex[:20]}", session["project_id"], sid,
                 session["owner_id"] or None, "user", body.message.strip(),
                 json.dumps({"attachments": [a.model_dump() for a in body.attachments]},
                            ensure_ascii=False) if body.attachments else None, now))
            conn.execute(
                "INSERT INTO review_messages(id, project_id, session_id, node_id, role,"
                " content, meta, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"rev_{uuid.uuid4().hex[:20]}", session["project_id"], sid,
                 session["owner_id"] or None, "assistant", reply,
                 json.dumps({"skill": body.skill, "model": r["model"],
                             "cost": r["usage"]["cost_total"],
                             "request_tokens": r["usage"]["request_tokens"],
                             "cached_tokens": r["usage"].get("cached_tokens", 0),
                             "suggestions": suggestions,
                             "limit_warning": limit_warning,
                             "parse_error": parse_error}, ensure_ascii=False), now))
        finish_task(tid, key,
                    result={"session_id": sid, "note": limit_warning,
                             "usage_total": r["usage"]["cost_total"],
                             "parse_error": parse_error},
                     usage_total=r["usage"]["cost_total"])
    except Exception as exc:  # noqa: BLE001 任务记录是唯一出口
        finish_task(tid, key, error=str(exc))


# ── A2 @引用对象清单(纯聚合读)──

@router.get("/refs")
def chat_refs(project_id: str) -> dict:
    with tx() as conn:
        chapters = [dict(r) for r in conn.execute(
            "SELECT id, title, status FROM outline_nodes"
            " WHERE project_id=? AND kind='chapter' ORDER BY sort_order", (project_id,)).fetchall()]
        entries = [dict(r) for r in conn.execute(
            "SELECT id, category, name FROM l1_entries"
            " WHERE project_id=? AND entry_status='confirmed'"
            " ORDER BY category, name", (project_id,)).fetchall()]
    hooks = [{"detail": f.detail, "status": f.status, "planted_chapter": f.planted_chapter}
             for f in load_world_state(project_id).foreshadowing_pool]
    return {"chapters": chapters, "entries": entries, "hooks": hooks}


class CompactIn(BaseModel):
    keep: int = COMPACT_KEEP   # 压缩后保留的最近原文条数(4~40 夹取)


@router.post("/{sid}/compact")
def compact_session(sid: str, body: CompactIn) -> dict:
    """批次三⑤:压缩本线——纯算法把更早轮次拼成"前情提要"常驻 system(零 LLM,
    原文全留库);此后装配=前情提要+最近 keep 条原文,前缀缓存只在压缩点付一次全价。"""
    info = _compact_session(sid, max(4, min(40, body.keep)))
    if info["compacted"] == 0:
        return {"ok": True, **info, "message": "本线不长,无需压缩"}
    return {"ok": True, **info,
            "message": f"已把更早 {info['compacted']} 轮拼入前情提要"
                       f"(最近 {COMPACT_KEEP} 条原文保留,原文仍在库)"}
