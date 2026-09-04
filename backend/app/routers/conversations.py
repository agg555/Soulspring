"""统一对话组件后端(A1/A2/A3,执行书 2026-08-31)。

- A3 多线会话:conversation_sessions 每节点可开多条命名对话线,消息挂 session_id;
- A4 发送即任务化(拍板:不做流式):复用 gen_tasks(kind='chat'),同线 running 即 409,
  轮询 /api/workbench/tasks/{tid} 与生成任务同款,live/replay 同源;
- A1 建议块:模型按 JSON 协议回 {reply, suggestions[]},解析失败降级纯文本标 parse_error
  (原文保留);采纳走两档:outline_field 轻档(人确认 diff 后写回节点字段+留痕)、
  chapter_text 重档(追加 patch 进该章变更集,走 AI 自修同管道,人改工作区再合入);
- A2 @引用:attachments 把章/角色/条目/伏笔内容拼进 system;默认上下文 = 面板选中节点
  (review 线自动附加章节正文,由 owner_id 决定)。
"""
from __future__ import annotations

import json
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..assembly import OUTLINE_KIND_LABEL, build_book_context, build_node_context
from ..audit.world_state import load_world_state
from ..common import EDGE_KINDS, EVENT_FIELDS, _load_skill_body, _now, _parse_frontmatter
from ..db import tx
from ..ledger.usage import chat_completion
from ..settings_store import get_settings
from .generation import _parse_json_loose
from .task_runner import (
    ACTIVE_NODES,
    TASK_LOCK,
    finish_task,
    heal_stale,
    set_stage,
    task_view,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

REVIEW_BASE_SYSTEM = (
    "你是网文审稿主编。作者会把章节正文发给你,你按作者选用的技能/要求进行审稿。"
    "只标记问题与给出修改建议,不直接改写正文;引用原文时给出位置。"
)

REPLY_PROTOCOL = """## 回复格式协议(必须遵守)
每次回复必须输出一个 JSON 对象,不要包 markdown 代码块:
{"reply": "给作者看的回复正文", "suggestions": [建议数组]}

建议数组每项格式:
{"quote": "引用的原文或现状(可空)", "issue": "问题是什么", "suggestion": "怎么改",
 "severity": "minor 或 major 或 critical",
 "target_type": "none 或 chapter_text 或 outline_field 或 event_field",
 "target": {...}}

- target_type="chapter_text":target={"node_id": "章节点 id", "revised_text": "按建议改写后的完整段落或全文,可直接替换原文"}
- target_type="outline_field":target={"node_id": "节点 id", "field": "title 或 summary 或 note", "value": "建议的新字段值"}
- target_type="event_field"(剧情时间线事件):target={"event_id": "事件 id", "field": "time_label 或 title 或 summary 或 line 或 status", "value": "建议的新值"}
- target_type="graph_field"(图谱节点/连线):target={"node_id" 或 "edge_id": "对象 id", "field": "label 或 sub_label(节点)/ label 或 kind(连线)", "value": "建议的新值"}
- target_type="graph_add"(建议新增图谱对象,人确认才落库):target={"board_id": "板 id", "item": {"type": "node", "label": "...", "sub_label": "..."} 或 {"type": "edge", "from_node_id": "...", "to_node_id": "...", "label": "...", "kind": "..."}}
- 无可落地的具体修改时 target_type 用 "none",target 传 {};没有建议时 suggestions 给 []
reply 面向作者;suggestions 是结构化建议,作者会逐条决定是否采纳。"""

OWNER_ACTIONS = {
    "review": "review_chat",
    "chat_test": "chat_test",
    "outline_node": "outline_chat",
    "branch": "outline_chat",
    "timeline_event": "outline_chat",
    "graph_node": "outline_chat",
    "graph_edge": "outline_chat",
    "graph_board": "outline_chat",
    "book": "book_chat",
}
AGENT_TYPES = {
    "review": "reviewer",
    "chat_test": "chat",
    "outline_node": "planner",
    "branch": "planner",
    "timeline_event": "planner",
    "graph_node": "planner",
    "graph_edge": "planner",
    "graph_board": "planner",
    "book": "planner",
}
VALID_OWNER_TYPES = {"review", "chat_test", "outline_node", "branch",
                     "timeline_event",
                     "graph_node", "graph_edge", "graph_board",
                     "book"}
# relation 会话类型已下线(2026-09-02 拍板):唯一 UI 入口 RelationGraphPanel 随 S10(a)
# 删除,relation_field 采纳分支同步下线;旧会话行留库只作历史,不再可建新线。
# C3 两个预设模式(执行书拍板:优化=针对节点给改法;奇思妙想=发散 3-5 个方向)
PRESET_PROMPTS = {
    "optimize": (
        "## 当前任务:优化模式\n"
        "针对上面给出的当前节点,找出可改进之处并给出具体改法。"
        "改大纲字段(标题/摘要/备注)的意见用 target_type=\"outline_field\" 的建议输出"
        "(field 选 title/summary/note,value 给出改后的完整新值);"
        "结构类意见(增删子节点、顺序调整)写在 reply 里,不强行造建议。"
    ),
    "ideas": (
        "## 当前任务:奇思妙想模式\n"
        "围绕当前节点做发散:给出 3-5 个互不重复、方向彼此不同的创作点子。"
        "每个点子输出为一条建议:issue=点子的一句话标题;"
        "suggestion=创意描述 + 为何在这个位置成立(结合上下文)+ 风险与代价;"
        "severity 按大胆程度自定;target_type 用 \"none\"(点子只供人挑选,不直接落库)。"
        "数量严格在 3-5 条之间,宁缺毋滥,不得换皮重复。"
    ),
    # 书级起步方向卡(骨架批执行书 §2 拍板:帮铺大纲/帮灌设定/帮写第一章)
    "book_outline": (
        "## 当前任务:帮铺大纲\n"
        "基于本书信息与下方大纲概要,给出或补全整体大纲结构:卷/近纲/章的层级划分、"
        "每部分一句话摘要。对已有节点的修改落 outline_field 建议(target={node_id, field, value},"
        "node_id 用大纲概要里的 id 原文);结构性新增(建卷/建章)写在 reply 里供作者确认,"
        "不要编造 node_id。"
    ),
    "book_setting": (
        "## 当前任务:帮灌设定\n"
        "围绕本书世界观与档案缺口做发散:指出大纲概要/近期章节暴露出的设定空洞,给出 3-5 条"
        "可落地的设定补全点子(力量体系/势力/地理/物品经济等)。每条 issue=一句话标题,"
        "suggestion=设定内容+为何成立+对主线的影响;target_type 用 \"none\",只供人挑选。"
    ),
    "book_first": (
        "## 当前任务:帮写第一章\n"
        "结合大纲概要里第一章的位置,给出第一章写作起步方案:开场场景、出场人物、核心冲突、"
        "钩子收尾(各一小段),并给 2-3 个风格不同的开篇方向供作者挑选;"
        "target_type 用 \"none\"。"
    ),
}


def _attach_chapter(node_id: str) -> str:
    """章节附件:优先正式正文,其次当前草稿(自原终审台迁入)。"""
    with tx() as conn:
        l4 = conn.execute("SELECT content FROM l4_texts WHERE node_id=?", (node_id,)).fetchone()
        if l4 and l4["content"]:
            return l4["content"]
        cs = conn.execute(
            "SELECT id FROM changesets WHERE node_id=? AND status IN ('draft','approved')"
            " ORDER BY created_at DESC LIMIT 1", (node_id,)).fetchone()
        if cs:
            p = conn.execute(
                "SELECT after FROM changeset_patches WHERE changeset_id=? AND field='content'"
                " ORDER BY version DESC LIMIT 1", (cs["id"],)).fetchone()
            if p:
                return p["after"]
    return ""


# ── 会话 CRUD ──

@router.get("")
def list_sessions(project_id: str = "", owner_type: str = "", owner_id: str = "") -> dict:
    sql = ("SELECT s.*,"
           " (SELECT COUNT(*) FROM review_messages m WHERE m.session_id = s.id) AS message_count,"
           " (SELECT MAX(m.created_at) FROM review_messages m WHERE m.session_id = s.id)"
           "   AS last_message_at"
           " FROM conversation_sessions s WHERE 1=1")
    params: list[str] = []
    if project_id:
        sql += " AND COALESCE(s.project_id,'') = ?"
        params.append(project_id)
    if owner_type:
        sql += " AND s.owner_type = ?"
        params.append(owner_type)
    if owner_id:
        sql += " AND s.owner_id = ?"
        params.append(owner_id)
    sql += " ORDER BY s.created_at"
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
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

class Attachment(BaseModel):
    type: str            # chapter | entry | hook
    id: str | None = None
    label: str = ""


class MessageIn(BaseModel):
    message: str
    skill: str | None = None
    temperature: float | None = None
    attachments: list[Attachment] = []
    preset: str | None = None      # outline_node/branch 线:optimize | ideas | None(自由聊)


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


def _attachments_section(attachments: list[Attachment]) -> str:
    """A2 @引用:把选中对象的正文拼进 system(章 20K / 条目 4K 截断)。"""
    blocks: list[str] = []
    for att in attachments[:8]:
        label = (att.label or "").strip()[:200]
        if att.type == "chapter" and att.id:
            content = _attach_chapter(att.id)
            if content:
                blocks.append(f"### 引用章:{label}\n\n{content[:20000]}")
        elif att.type == "entry" and att.id:
            with tx() as conn:
                row = conn.execute(
                    "SELECT name, category, content FROM l1_entries WHERE id=?",
                    (att.id,)).fetchone()
            if row:
                blocks.append(
                    f"### 引用条目({row['category']}):{row['name']}\n\n{row['content'][:4000]}")
        elif att.type == "hook":
            blocks.append(f"### 引用伏笔:{label}")
    if not blocks:
        return ""
    return "## 作者手动引用的上下文(@引用)\n\n" + "\n\n".join(blocks)


def _preset_part(body: MessageIn, free_text: str | None = None) -> list[str]:
    """C3 预设模式(优化/奇思妙想);未中预设时给自由对话文案(None=不追加)。"""
    preset = body.preset if body.preset in PRESET_PROMPTS else None
    if preset:
        return [PRESET_PROMPTS[preset]]
    return [free_text] if free_text else []


def _context_review(session: dict, body: MessageIn) -> list[str]:
    """审稿线:技能体 + 章正文 + 结构化建议的 target 锚定。"""
    parts: list[str] = [REVIEW_BASE_SYSTEM]
    if body.skill:
        parts.append(f"## 启用技能:{body.skill}\n\n{_load_skill_body(body.skill)}")
    chapter = _attach_chapter(session["owner_id"])
    if chapter:
        parts.append("## 审稿对象(章节正文)\n\n" + chapter[:20000])
    else:
        parts.append("(本章暂无正文,作者可能在进行纯咨询)")
    # 建议 target 必须能落地:把当前章 node_id 明确告知模型(实测缺失会导致
    # outline_field/chapter_text 建议的 node_id 被填成标题文本,采纳时 404)
    with tx() as conn:
        nrow = conn.execute(
            "SELECT id, title FROM outline_nodes WHERE id=?",
            (session["owner_id"],)).fetchone()
    if nrow:
        parts.append(
            "## 当前上下文(结构化建议的 target 必须引用)\n"
            f"- 当前章节点 id:`{nrow['id']}`\n"
            f"- 当前章标题:{nrow['title']}\n"
            "- target_type=chapter_text 或 outline_field 时,target.node_id 必须填上述 id 原文。")
    return parts


def _context_chat_test(session: dict, body: MessageIn) -> list[str]:
    return ["你是 Soulspring 的对话助手(当前为测试对话线,回答简洁即可)。"]


def _context_outline_node(session: dict, body: MessageIn) -> list[str]:
    """C3 节点级对话:上下文 = 祖先链 + 本节点字段 + L1 常驻(build_node_context 裁剪)。"""
    parts: list[str] = []
    node_pid = session["project_id"]
    if node_pid:
        try:
            parts.append(build_node_context(node_pid, session["owner_id"]))
        except ValueError:
            parts.append("(节点上下文加载失败:节点不存在)")
    parts.extend(_preset_part(
        body,
        "## 当前任务:自由对话\n"
        "围绕当前节点与作者讨论;有具体可落地的字段改法时用 outline_field 建议输出。"))
    return parts


def _context_branch(session: dict, body: MessageIn) -> list[str]:
    """C4 分支会话:上下文 = 主干节点现状 + 本分支草稿包(改的都是草稿,主干不动)。"""
    parts: list[str] = []
    with tx() as conn:
        brow = conn.execute(
            "SELECT branch_payload, status FROM conversation_sessions WHERE id=?",
            (session["id"],)).fetchone()
    payload = {}
    if brow and brow["branch_payload"]:
        try:
            payload = json.loads(brow["branch_payload"])
        except json.JSONDecodeError:
            payload = {}
    node_pid = session["project_id"]
    if node_pid:
        try:
            parts.append(build_node_context(node_pid, session["owner_id"]))
        except ValueError:
            pass
    parts.append(
        "## 本分支的节点字段草稿(你的建议应基于草稿,而非主干现状)\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
        + "\n(分支内改字段走草稿,作者确认[转正]后才写回主干并留版本历史)")
    parts.extend(_preset_part(body))
    return parts


def _context_timeline_event(session: dict, body: MessageIn) -> list[str]:
    """第三批 E:事件级对话 = 事件字段 + 关联章摘要(正文前 500 字,守装配纪律)。"""
    parts: list[str] = []
    with tx() as conn:
        erow = conn.execute(
            "SELECT * FROM timeline_events WHERE id=?", (session["owner_id"],)).fetchone()
        chapters = [dict(c) for c in conn.execute(
            "SELECT n.id, n.title FROM event_chapters ec"
            " JOIN outline_nodes n ON n.id = ec.node_id WHERE ec.event_id=?",
            (session["owner_id"],)).fetchall()]
    if erow is None:
        parts.append("(事件已被删除)")
    else:
        evt = dict(erow)
        evt.pop("created_at", None)
        parts.append(
            "## 当前剧情时间线事件(你的建议针对这个事件;event_id=`"
            + session["owner_id"] + "`)\n"
            + json.dumps(evt, ensure_ascii=False, indent=1))
        for c in chapters:
            with tx() as conn:
                l4 = conn.execute(
                    "SELECT content FROM l4_texts WHERE node_id=?", (c["id"],)).fetchone()
            head = (l4["content"][:500] + "…") if l4 and l4["content"] else "(该章暂无正文)"
            parts.append(
                f"### 关联章:{c['title']}(chapter_text 建议的 node_id 必须用 `{c['id']}`)\n{head}")
    parts.extend(_preset_part(
        body,
        "## 当前任务:自由对话\n"
        "围绕该事件讨论;事件字段(time_label/title/summary/line/status)的改法"
        "用 target_type=\"event_field\" 的建议输出(event_id 用上方给出的 id 原文)。"))
    return parts


def _context_graph(session: dict, body: MessageIn) -> list[str]:
    """第四批 D:图谱对象对话——节点(含相连边与邻居卡)/边(两端节点卡)/整板摘要。"""
    parts: list[str] = []
    owner_type = session["owner_type"]
    with tx() as conn:
        if owner_type == "graph_node":
            node = conn.execute(
                "SELECT * FROM graph_nodes WHERE id=?", (session["owner_id"],)).fetchone()
            if node is None:
                parts.append("(图谱节点已被删除)")
            else:
                nd = dict(node)
                edges = [dict(e) for e in conn.execute(
                    "SELECT * FROM graph_edges WHERE from_node_id=? OR to_node_id=?",
                    (session["owner_id"], session["owner_id"])).fetchall()]
                neigh_ids = {e["from_node_id"] if e["to_node_id"] == session["owner_id"]
                             else e["to_node_id"] for e in edges}
                neighbours = [dict(n) for n in conn.execute(
                    f"SELECT id, label, sub_label FROM graph_nodes WHERE id IN "
                    f"({','.join('?' for _ in neigh_ids) or "''"})",
                    list(neigh_ids)).fetchall()] if neigh_ids else []
                parts.append(
                    "## 当前图谱节点(建议针对它;node_id=`" + session["owner_id"]
                    + "`;所属板 board_id=`" + str(nd.get("board_id") or "")
                    + "`——graph_add 建议的 board_id 必须用此值)\n"
                    + json.dumps({k: nd[k] for k in ("label", "sub_label", "x", "y")},
                                 ensure_ascii=False)
                    + "\n相连连线:" + json.dumps(
                        [{k: e[k] for k in ("label", "kind")} for e in edges],
                        ensure_ascii=False)
                    + "\n邻居节点:" + json.dumps(neighbours, ensure_ascii=False))
        elif owner_type == "graph_edge":
            edge = conn.execute(
                "SELECT * FROM graph_edges WHERE id=?", (session["owner_id"],)).fetchone()
            if edge is None:
                parts.append("(图谱连线已被删除)")
            else:
                e = dict(edge)
                ends = {}
                for nid_ in (e["from_node_id"], e["to_node_id"]):
                    n = conn.execute(
                        "SELECT id, label FROM graph_nodes WHERE id=?", (nid_,)).fetchone()
                    ends[nid_] = n["label"] if n else "(已删节点)"
                parts.append(
                    "## 当前图谱连线(建议针对它;edge_id=`" + session["owner_id"] + "` )\n"
                    + json.dumps({**{k: e[k] for k in ("label", "kind")},
                                  "from": ends[e["from_node_id"]],
                                  "to": ends[e["to_node_id"]]},
                                 ensure_ascii=False, indent=1))
        else:  # graph_board:整板摘要,6000 上限裁剪
            board = conn.execute(
                "SELECT * FROM graph_boards WHERE id=?", (session["owner_id"],)).fetchone()
            if board is None:
                parts.append("(图谱板已被删除)")
            else:
                nodes = [dict(n) for n in conn.execute(
                    "SELECT id, label, sub_label FROM graph_nodes WHERE board_id=?"
                    " ORDER BY created_at", (session["owner_id"],)).fetchall()]
                edges = [dict(e) for e in conn.execute(
                    "SELECT label, kind, from_node_id, to_node_id FROM graph_edges"
                    " WHERE board_id=? ORDER BY created_at", (session["owner_id"],)).fetchall()]
                name_of = {n["id"]: n["label"] for n in nodes}
                edge_lines = [
                    f"{name_of.get(e['from_node_id'], '?')} --{e['kind']}"
                    f"{'·' + e['label'] if e['label'] else ''}--> "
                    f"{name_of.get(e['to_node_id'], '?')}" for e in edges]
                text = (
                    f"板:{board['name']}(board_id=`{session['owner_id']}`)\n"
                    + "节点(id → label):"
                    + "; ".join(f"`{n['id']}` → {n['label']}" for n in nodes)
                    + "\n连线(" + str(len(edges)) + "):\n" + "\n".join(edge_lines))
                parts.append(
                    "## 当前图谱板整板(建议针对该板;"
                    "graph_add 的 board_id 与 from/to_node_id 必须用上方 id 原文)\n"
                    + text[:6000])
    parts.extend(_preset_part(
        body,
        "## 当前任务:自由对话\n"
        "围绕该图谱对象讨论;字段改法用 target_type=\"graph_field\" 建议"
        "(target={node_id 或 edge_id, field, value});"
        "建议新增节点或连线时用 target_type=\"graph_add\""
        "(target={board_id, item:{type:\"node\", label, sub_label?} 或 "
        "{type:\"edge\", from_node_id, to_node_id, label, kind}}),人确认后才落库。"))
    return parts


def _context_book(session: dict, body: MessageIn) -> list[str]:
    """书级对话(骨架批执行书 §2,owner_id=project_id):书信息+大纲概要+近期章节
    +L1 常驻摘要(build_book_context,6000 上限)。双重性格:既传统问答,也可出
    结构化建议走采纳闸门——target 沿用现有类型,上下文给足 id。"""
    parts = [build_book_context(session["owner_id"])]
    parts.extend(_preset_part(
        body,
        "## 当前任务:书级对话\n"
        "围绕整本书协作:铺大纲/灌设定/推剧情/改字段都行。结构化建议 target 沿用:"
        "改大纲字段用 outline_field(target={node_id, field, value},node_id 用大纲概要"
        "里的 id 原文);改图谱对象用 graph_field;改章正文用 chapter_text"
        "(target={node_id, field:\"content\", value},进写章工作台变更集人审合入);"
        "新增图谱节点/连线用 graph_add(target={board_id, item})。"))
    return parts


# owner_type → 上下文组装函数表(S5);未知类型走兜底文案(校验已挡,防御保留)
_CONTEXT_BUILDERS = {
    "review": _context_review,
    "chat_test": _context_chat_test,
    "outline_node": _context_outline_node,
    "branch": _context_branch,
    "timeline_event": _context_timeline_event,
    "graph_node": _context_graph,
    "graph_edge": _context_graph,
    "graph_board": _context_graph,
    "book": _context_book,
}


def _system_parts(session: dict, body: MessageIn) -> list[str]:
    """组装 system 消息:owner_type 上下文块 + 回复协议 + @引用。"""
    builder = _CONTEXT_BUILDERS.get(session["owner_type"])
    if builder is None:  # pragma: no cover — create_session 校验已挡未知类型
        parts = ["你是网文创作助手,围绕作者给出的节点上下文协作。"]
    else:
        parts = builder(session, body)
    parts.append(REPLY_PROTOCOL)
    att_section = _attachments_section(body.attachments)
    if att_section:
        parts.append(att_section)
    return parts


def _history(sid: str, limit: int = 40) -> list[dict]:
    # 40 条:组装进 prompt 的历史上限口径(经验值,单次调用 token 预算内;更早轮次截断)
    with tx() as conn:
        rows = conn.execute(
            "SELECT role, content FROM review_messages WHERE session_id=?"
            " ORDER BY created_at, rowid LIMIT ?", (sid, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _parse_reply(raw: str) -> tuple[str, list[dict], bool]:
    """A1 建议协议解析;失败降级纯文本(parse_error=True,原文完整保留)。"""
    try:
        data = _parse_json_loose(raw)
        reply = str(data.get("reply", "") or "").strip()
        raw_suggestions = data.get("suggestions")
        if not isinstance(raw_suggestions, list):
            raw_suggestions = []
        if not reply and not raw_suggestions:
            raise ValueError("reply 与 suggestions 均为空")
        clean: list[dict] = []
        for s in raw_suggestions[:10]:
            if not isinstance(s, dict):
                continue
            tt = s.get("target_type")
            clean.append({
                "quote": str(s.get("quote") or ""),
                "issue": str(s.get("issue") or ""),
                "suggestion": str(s.get("suggestion") or ""),
                "severity": s.get("severity") if s.get("severity") in ("minor", "major", "critical") else "minor",
                "target_type": tt if tt in ("none", "chapter_text", "outline_field",
                                            "event_field",
                                            "graph_field", "graph_add") else "none",
                "target": s.get("target") if isinstance(s.get("target"), dict) else {},
            })
        return reply, clean, False
    except (ValueError, json.JSONDecodeError):
        return raw.strip(), [], True


def _run_chat_turn(tid: str, sid: str, body: MessageIn) -> None:
    """后台线程:组装上下文 → 调模型 → 解析建议协议 → 消息落库 → 任务收尾。"""
    key = f"chat:{sid}"
    try:
        set_stage(tid, "calling")
        session = _get_session(sid)
        messages = [
            {"role": "system", "content": "\n\n".join(_system_parts(session, body))},
            *_history(sid),
            {"role": "user", "content": body.message.strip()},
        ]
        action = OWNER_ACTIONS.get(session["owner_type"], "chat_test")
        r = chat_completion(
            messages, action=action, project_id=session["project_id"],
            agent_type=AGENT_TYPES.get(session["owner_type"], "chat"),
            input_summary=body.message[:200], temperature_override=body.temperature,
            # 8000:对话类回包含思考 + JSON 协议正文(M6 实测缺省会被思考链吃满)
            max_tokens_override=8000)
        reply, suggestions, parse_error = _parse_reply(r["content"])
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
                             "cost": r["usage"]["cost_total"], "suggestions": suggestions,
                             "parse_error": parse_error}, ensure_ascii=False), now))
        finish_task(tid, key,
                     result={"session_id": sid, "note": None,
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
