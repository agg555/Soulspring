"""对话上下文组装(A1/A2/C3/C4/书级/图谱/档案,2026-09-10 自 conversations.py 抽出,
纯移动零行为变化——大工程②A 拆大文件第二批,conv_parse.py 同款先例)。

- system 拼装链:_system_parts = owner_type 上下文块(_CONTEXT_BUILDERS 分发表)
  + 前情提要 digest + 触点追加词 + 参考提示词 + REPLY_PROTOCOL + @引用段;
- 每种 owner_type 一个 _context_* 组装器(审稿/测试/节点/分支/构思/事件/图谱/书/档案);
- PRESET_PROMPTS 内置预设指令与 MessageIn/Attachment 请求模型同住本件;
- 懒导入保持原位(_context_idea→ideas、_context_l1→l1:运行时才 import,无导入环);
  conversations.py 侧对测试用的旧路径做 re-export(MessageIn/_system_parts/
  REPLY_PROTOCOL 等),导入路径零破坏。
"""
from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import BaseModel

from ..assembly import build_book_context, build_node_context
from ..common import _load_skill_body
from ..db import tx
from ..settings_store import ref_prompt_section, touch_prompt_append

REVIEW_BASE_SYSTEM = (
    "你是网文审稿主编。作者会把章节正文发给你,你按作者选用的技能/要求进行审稿。"
    "只标记问题与给出修改建议,不直接改写正文;引用原文时给出位置。"
)

REPLY_PROTOCOL = """## 回复格式协议(必须遵守)
每次回复必须输出一个 JSON 对象,不要包 markdown 代码块:
{"reply": "给作者看的回复正文", "suggestions": [建议数组]}

输出纪律:字符串值内的换行必须写成 \\n 转义,禁止在 JSON 内输出真实换行或回车
(裸换行会破坏解析);回复正文不用 emoji,除非作者明确要求。
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
- target_type="subtopic_add"(建议给节点新增子题树,人确认才落库):target={"node_id": "节点 id", "tree": [{"title": "子题标题", "children": [{"title": "更深层子题,可继续嵌套"}]}]}
- 无可落地的具体修改时 target_type 用 "none",target 传 {};没有建议时 suggestions 给 []
reply 面向作者;suggestions 是结构化建议,作者会逐条决定是否采纳。
无论如何,你的输出必须是一个单独的 JSON 对象,不要在 JSON 之外加任何文字或代码块围栏。"""

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
    "l1": "l1_chat",
    "idea": "outline_chat",
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
    "l1": "builder",
    "idea": "planner",
}
VALID_OWNER_TYPES = {"review", "chat_test", "outline_node", "branch",
                     "timeline_event",
                     "graph_node", "graph_edge", "graph_board",
                     "book", "l1", "idea"}
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
    "book_outline_review": (
        "## 当前任务:大纲体检\n"
        "对下方大纲概要做结构性体检,逐项检查:①断头章(有章无卷/近纲归属)②孤立卷"
        "(卷下无章)③章节密度失衡(某近纲下章数过多/过少)④钩子与节奏(相邻章标题连读"
        "是否缺推进)⑤命名一致性。每条可落地的字段修正(改标题/摘要)用 outline_field 建议"
        "(node_id 用大纲概要里的 id 原文);结构性意见(需要增删节点)写在 reply 里供作者"
        "确认,不要编造 node_id。结论按 严重度 排序,不超过 8 条。"
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


class Attachment(BaseModel):
    type: str            # chapter | entry | hook | file(批次三①:txt/md 文件附件)
    id: str | None = None
    label: str = ""
    text: str = ""       # file 型:前端读入的全文(截 8K,零上传盘;txt/md 两种)


class MessageIn(BaseModel):
    message: str
    skill: str | None = None
    temperature: float | None = None
    attachments: list[Attachment] = []
    preset: str | None = None      # outline_node/branch 线:optimize | ideas | None(自由聊)
    # 自定义模板填空指令(2026-09-09 拍板:选择填空式模板;前端组装,注入 system
    # 与 preset 同位;限 4000 字防滥用)。与 preset 可同发(内置模板=协议段+填空)。
    preset_text: str | None = None
    # 参考提示词运行时手选(2026-09-10 扩到对话线):仅手选生效(非 None 才注入),
    # 三层绑定链不作用于对话——防止全局绑定悄悄改变所有对话的行为。
    ref_prompt_ids: list[str] | None = None
    thinking: str | None = None    # 对话台思考档直选(low/high/max/off;空=按动作档位;off=DeepSeek 非思考,GLM 回落默认)


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
        elif att.type == "file":
            # 批次三①:文件附件(txt/md,前端读入直传,不落盘不进库;超 8K 截断)
            raw = (att.text or "").strip()
            name = label or "附件"
            blocks.append(f"### 附件文件:{name}\n\n{raw[:8000]}"
                          + ("…(超 8K 截断)" if len(raw) > 8000 else ""))
    if not blocks:
        return ""
    return "## 作者手动引用的上下文(@引用)\n\n" + "\n\n".join(blocks)


def _preset_part(body: MessageIn, free_text: str | None = None) -> list[str]:
    """C3 预设模式(优化/奇思妙想)+自定义模板填空(2026-09-09)。
    内置 preset=协议指引段;preset_text=作者填空的模板指令段;两者可叠加。
    有任一指令段时不再回落 free_text(指令已表达任务意图)。"""
    parts: list[str] = []
    preset = body.preset if body.preset in PRESET_PROMPTS else None
    if preset:
        parts.append(PRESET_PROMPTS[preset])
    fill = (body.preset_text or "").strip()
    if fill:
        parts.append("## 作者模板填空指令(按此执行;空缺项按你的判断补全)\n" + fill[:4000])
    if parts:
        return parts
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


def _context_idea(session: dict, body: MessageIn) -> list[str]:
    """构思树子讨论(批次七⑤):父链层叠摘要(根→自身,每层标题+备注+状态,
    有历史线的层带上纯算法 digest)进 system;链上任一 dropped=冻结不喂 AI
    (在 LLM 调用前抛错,任务落可读 error,零 token 消耗)。"""
    from .ideas import chain_for_context, latest_parent_digest
    chain = chain_for_context(session["owner_id"])
    dropped = [i for i in chain if i["status"] == "dropped"]
    if dropped:
        raise HTTPException(
            409, f"构思「{dropped[0]['title']}」已放弃(冻结不喂 AI);回待议后才能继续对话")
    lines = []
    status_label = {"open": "待议", "adopted": "已采纳", "dropped": "已放弃"}
    for i in chain:
        mark = "▸ 本线" if i["id"] == session["owner_id"] else "·"
        line = f"{mark} {i['title']}[{status_label[i['status']]}]"
        if i["note"]:
            line += f":{i['note']}"
        if i["id"] != session["owner_id"]:
            d = latest_parent_digest(i["id"])
            if d:
                line += f"\n  └ 该层前情提要:{d[:400]}"
        lines.append(line)
    parts = ["## 构思树·父链(从根到本线;建议照常走采纳闸门,采纳状态只作共识标记)\n"
             + "\n".join(lines)]
    parts.extend(_preset_part(
        body,
        "## 当前任务:构思子线讨论\n"
        "围绕这条构思(及其父链)与作者深聊;能落成具体字段改法时用对应 target_type"
        " 建议(采纳闸门照常),纯发散就写 reply。"))
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


def _context_l1(session: dict, body: MessageIn) -> list[str]:
    """L1 档案库对话(批次二 AI 流升级):六类计数+全部条目名录(正式+提案)。
    档案字段无采纳通路,建议一律 target_type=none,讨论与点子为主。"""
    from .l1 import CATEGORY_LABELS
    with tx() as conn:
        book = conn.execute("SELECT name, genre FROM projects WHERE id=?",
                            (session["owner_id"],)).fetchone()
        rows = conn.execute(
            "SELECT category, name, entry_status FROM l1_entries WHERE project_id=?"
            " ORDER BY category, name", (session["owner_id"],)).fetchall()
    lines = [f"书名《{book['name']}》({book['genre'] or '类型未填'})" if book else "(书不存在)"]
    by_cat: dict[str, list[str]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(
            r["name"] + ("(提案)" if r["entry_status"] == "proposal" else ""))
    for cat, names in by_cat.items():
        label = CATEGORY_LABELS.get(cat, cat)
        lines.append(f"{label}({len(names)}):" + ";".join(names))
    parts = ["## 当前 L1 档案库现状\n" + "\n".join(lines) if lines else "(档案为空)"]
    parts.extend(_preset_part(
        body,
        "## 当前任务:档案库讨论\n"
        "围绕 L1 档案协作:查缺口/想设定/评条目都行。档案字段暂无结构化采纳通路,"
        "输出 target_type 用 \"none\",内容写在 reply 里。"))
    return parts


# owner_type → 上下文组装函数表(S5);未知类型走兜底文案(校验已挡,防御保留)
_CONTEXT_BUILDERS = {
    "review": _context_review,
    "chat_test": _context_chat_test,
    "outline_node": _context_outline_node,
    "branch": _context_branch,
    "idea": _context_idea,
    "timeline_event": _context_timeline_event,
    "graph_node": _context_graph,
    "graph_edge": _context_graph,
    "graph_board": _context_graph,
    "book": _context_book,
    "l1": _context_l1,
}


def _system_parts(session: dict, body: MessageIn) -> list[str]:
    """组装 system 消息:owner_type 上下文块 + 前情提要(如有) + 回复协议 + @引用。"""
    builder = _CONTEXT_BUILDERS.get(session["owner_type"])
    if builder is None:  # pragma: no cover — create_session 校验已挡未知类型
        parts = ["你是网文创作助手,围绕作者给出的节点上下文协作。"]
    else:
        parts = builder(session, body)
    digest = (session.get("digest") or "").strip()
    if digest:
        # 批次三⑤:前情提要常驻 system(纯算法拼接;原文全留库,本线可随时再压缩)
        parts.append(digest)
    # 批次六甲:触点级提示词追加(只追加不替换;插在 REPLY_PROTOCOL 之前)
    touch_append = touch_prompt_append(OWNER_ACTIONS.get(session["owner_type"], "chat_test"))
    if touch_append:
        parts.append(touch_append)
    # 参考提示词(2026-09-10 扩到对话线):仅运行时手选生效,注入段插在协议之前
    if body.ref_prompt_ids is not None:
        rp = ref_prompt_section(OWNER_ACTIONS.get(session["owner_type"], "chat_test"),
                                session.get("project_id"), body.ref_prompt_ids)
        if rp:
            parts.append(rp)
    parts.append(REPLY_PROTOCOL)
    att_section = _attachments_section(body.attachments)
    if att_section:
        parts.append(att_section)
    return parts
