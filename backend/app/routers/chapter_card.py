"""章节信息卡 API(二期③,分支打磨 §三;消费者 a+b 已拍板)。

四行直写既有表(白名单;零 L1/L2 写入,零闸门绕行——全是"人的操作直生效"语义):
1. 一句话大纲 → outline_nodes.summary(进大纲树/装配);
2. 时间关联 → event_chapters(差异同步);
3. 本章人物 → 人物板"同框"边(kind='同框', style.at_chapter=章号,星形挂首个
   选中人物;只允许引用人物板既有节点,不造新人)。有场景的章返回场景聚合并
   引导去场景卡(R3:防第二事实源)。章号从标题提取(第N章),与人物关系时间轴
   同口径;
4. 备注 → outline_nodes.note。

消费者(无消费者不建字段的拍板兑现):
- a 装配增强:assembly.build_assembly 按同框边注入本章人物 L1 条目(按需精准);
- b 体检新规:diagnostics 两条新规(人物未登场先用/图谱名与档案名不一)。
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx

router = APIRouter(prefix="/api/card", tags=["chapter-card"])

SAME_FRAME_KIND = "同框"   # 本章人物边类别(管理边,区别于手画关系边)


def chapter_no(title: str) -> int | None:
    m = re.search(r"第(\d+)章", title or "")
    return int(m.group(1)) if m else None


def _get_chapter(conn, pid: str, nid: str) -> dict:
    row = conn.execute(
        "SELECT * FROM outline_nodes WHERE id=? AND project_id=?", (nid, pid)).fetchone()
    if row is None:
        raise HTTPException(404, "章节点不存在")
    if row["kind"] != "chapter":
        raise HTTPException(422, "章节信息卡只用于章节点")
    return dict(row)


def _edge_style(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _cast_nodes(conn, pid: str, no: int) -> set[str]:
    """本章同框边触及的人物图节点 id 集(管理边:kind=同框 且 at_chapter=章号)。"""
    return {r["nid"] for r in conn.execute(
        "SELECT DISTINCT n.id AS nid FROM graph_edges e"
        " JOIN graph_nodes n ON n.id IN (e.from_node_id, e.to_node_id)"
        " JOIN graph_boards b ON b.id = e.board_id"
        " WHERE b.project_id=? AND b.kind='character'"
        " AND e.kind=? AND json_extract(e.style, '$.at_chapter')=?",
        (pid, SAME_FRAME_KIND, no))}


class CardIn(BaseModel):
    summary: str | None = None
    note: str | None = None
    event_ids: list[str] | None = None
    cast_node_ids: list[str] | None = None


@router.get("/{nid}")
def get_card(nid: str, pid: str) -> dict:
    with tx() as conn:
        node = _get_chapter(conn, pid, nid)
        no = chapter_no(node["title"])
        events = [dict(r) for r in conn.execute(
            "SELECT id, title, time_label, line, status FROM timeline_events"
            " WHERE project_id=? ORDER BY sort_key", (pid,))]
        linked = {r["event_id"] for r in conn.execute(
            "SELECT event_id FROM event_chapters WHERE node_id=?", (nid,))}
        # 人物板既有节点(只引用已有人物)
        characters = [dict(r) for r in conn.execute(
            "SELECT n.id, n.label, n.ref_id FROM graph_nodes n"
            " JOIN graph_boards b ON b.id = n.board_id"
            " WHERE b.project_id=? AND b.kind='character' ORDER BY b.name, n.label", (pid,))]
        cast_ids = sorted(_cast_nodes(conn, pid, no)) if no is not None else []
        # 场景聚合(R3):有场景的章,人物以场景五字段为准
        scenes = [dict(r) for r in conn.execute(
            "SELECT id, title, scene_fields FROM outline_nodes"
            " WHERE parent_id=? AND kind='scene'", (nid,))]
        scene_cast: list[str] = []
        for s in scenes:
            try:
                sf = json.loads(s["scene_fields"] or "{}")
            except json.JSONDecodeError:
                sf = {}
            scene_cast.extend(sf.get("characters") or [])
    return {
        "node_id": nid, "title": node["title"], "chapter_no": no,
        "summary": node["summary"] or "", "note": node["note"] or "",
        "events": events, "linked_event_ids": sorted(linked),
        "characters": characters, "cast_node_ids": cast_ids,
        "has_scenes": bool(scenes),
        "scene_cast": sorted(set(scene_cast)),
    }


class CardAiFillIn(BaseModel):
    hint: str = ""
    # 参考提示词运行时手选(2026-09-10;None=走绑定链:书>触点>全局)
    ref_prompt_ids: list[str] | None = None


@router.post("/{nid}/ai-fill")
def card_ai_fill(nid: str, pid: str, body: CardAiFillIn | None = None) -> dict:
    """AI 预填章节卡(候选清单落地批 A):AI 读本章正文出四行建议,**不落库**——
    前端 diff 确认后由人调 PUT(人的点击=批准闸门)。只允许引用既有事件名录与
    人物板节点,模型造不出新对象。"""
    from ..ledger.usage import chat_completion
    from ..settings_store import ref_prompt_section, touch_prompt_append
    from .generation import _parse_json_loose

    with tx() as conn:
        node = _get_chapter(conn, pid, nid)
        text = conn.execute(
            "SELECT content FROM l4_texts WHERE node_id=?", (nid,)).fetchone()
        if text is None or not text["content"].strip():
            raise HTTPException(422, "本章还没有正文(先在工作台生成或粘贴)")
        events = [dict(r) for r in conn.execute(
            "SELECT id, title FROM timeline_events WHERE project_id=? ORDER BY sort_key",
            (pid,))]
        characters = [dict(r) for r in conn.execute(
            "SELECT DISTINCT n.label FROM graph_nodes n"
            " JOIN graph_boards b ON b.id = n.board_id"
            " WHERE b.project_id=? AND b.kind='character' AND n.ref_type='l1_entry'"
            " ORDER BY n.label", (pid,))]
    from ..common import _prompt
    system = _prompt("章节-卡片预填.md", {
        "{{CHAPTER_TEXT}}": text["content"][:12000],
        "{{EVENT_LIST}}": ";".join(e["title"] for e in events) or "(尚无事件)",
        "{{CHARACTER_LIST}}": ";".join(c["label"] for c in characters) or "(尚无人物)",
        "{{USER_HINT}}": (body.hint or "").strip() if body else "",
    })
    system += ref_prompt_section("chapter_card_fill", pid,
                                 body.ref_prompt_ids if body else None)
    system += touch_prompt_append("chapter_card_fill")
    try:
        r = chat_completion(
            [{"role": "system", "content": system},
             {"role": "user", "content": "请严格按系统指令输出 JSON。"}],
            action="chapter_card_fill", project_id=pid, node_id=nid,
            agent_type="planner", input_summary=f"章节卡预填:{node['title'][:40]}")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"模型调用失败:{exc}")
    try:
        data = _parse_json_loose(r["content"])
    except ValueError as exc:
        raise HTTPException(502, f"模型输出不是合法 JSON({exc});可重试")
    known_labels = {c["label"] for c in characters}
    event_titles = {e["title"] for e in events}
    sug_events = data.get("events") or []
    return {
        "summary": str(data.get("summary") or "")[:500],
        "note": str(data.get("note") or "")[:500],
        # 事件/人物仅收录名录内命中项(防模型编造);事件按名录 id 回传供直写端点
        "event_titles": [t for t in sug_events if t in event_titles][:5],
        "character_labels": [c for c in (data.get("characters") or [])
                             if c in known_labels][:8],
        "cost": r["usage"]["cost_total"],
    }


@router.put("/{nid}")
def save_card(nid: str, pid: str, body: CardIn) -> dict:
    with tx() as conn:
        node = _get_chapter(conn, pid, nid)
        no = chapter_no(node["title"])
        sets, args = [], []
        if body.summary is not None:
            sets.append("summary=?"); args.append(body.summary.strip())
        if body.note is not None:
            sets.append("note=?"); args.append(body.note.strip())
        if sets:
            args.extend([_now(), nid])
            conn.execute(f"UPDATE outline_nodes SET {', '.join(sets)}, updated_at=? WHERE id=?",
                         args)
        # 时间关联:差异同步 event_chapters
        if body.event_ids is not None:
            known = {r["id"] for r in conn.execute(
                "SELECT id FROM timeline_events WHERE project_id=?", (pid,))}
            want = set(body.event_ids) & known
            have = {r["event_id"] for r in conn.execute(
                "SELECT event_id FROM event_chapters WHERE node_id=?", (nid,))}
            for gone in have - want:
                conn.execute("DELETE FROM event_chapters WHERE event_id=? AND node_id=?",
                             (gone, nid))
            for add in want - have:
                conn.execute("INSERT OR IGNORE INTO event_chapters(event_id, node_id)"
                             " VALUES(?,?)", (add, nid))
        # 本章人物:同框边差异同步(星形挂首个选中人物;单人不建边,提示去场景卡)。
        # 管理边=本卡片生的(kind=同框+本章 at_chapter),每次保存全量重建——
        # 星形边服务两端成员,"逐条增删"无法表达拆人,重建语义最简且幂等。
        if body.cast_node_ids is not None:
            if no is None:
                raise HTTPException(422, "章标题无「第N章」编号,无法标同框章号"
                                        "(人物关系时间轴口径)")
            valid = {r["id"] for r in conn.execute(
                "SELECT n.id FROM graph_nodes n JOIN graph_boards b ON b.id=n.board_id"
                " WHERE b.project_id=? AND b.kind='character'", (pid,))}
            want = [c for c in body.cast_node_ids if c in valid]
            if len(want) == 1:
                raise HTTPException(422, "本章人物至少选 2 人(同框关系边需要两端;"
                                        "单人出场请记场景卡)")
            managed = [r["id"] for r in conn.execute(
                "SELECT e.id FROM graph_edges e"
                " JOIN graph_boards b ON b.id = e.board_id"
                " WHERE b.project_id=? AND b.kind='character'"
                " AND e.kind=? AND json_extract(e.style, '$.at_chapter')=?",
                (pid, SAME_FRAME_KIND, no))]
            for eid in managed:
                conn.execute("DELETE FROM graph_edges WHERE id=?", (eid,))
            if len(want) >= 2:
                hub = want[0]
                board_id = _board_of(conn, pid, hub)
                for c in want[1:]:
                    conn.execute(
                        "INSERT INTO graph_edges(id, board_id, from_node_id, to_node_id,"
                        " label, kind, style, created_at, updated_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (f"ge_{no}_{c[:8]}_{hub[:8]}", board_id, hub, c,
                         f"第{no}章同框", SAME_FRAME_KIND,
                         json.dumps({"at_chapter": no}, ensure_ascii=False), _now(), _now()))
    return {"ok": True}


def _board_of(conn, pid: str, node_id: str) -> str:
    row = conn.execute(
        "SELECT b.id FROM graph_boards b JOIN graph_nodes n ON n.board_id=b.id"
        " WHERE n.id=? AND b.project_id=?", (node_id, pid)).fetchone()
    if row is None:
        raise HTTPException(422, "人物节点所在板不存在")
    return row["id"]
