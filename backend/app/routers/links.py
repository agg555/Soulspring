"""B3 实体互链(骨架批批次一,执行书 2026-09-03 §3,2026-09-04 实施):
点任意实体(大纲节点/图谱节点/时间线事件/L1 条目)→ 聚合展示其关联对象,可跳转。

数据源(按实体类型定聚合查询,执行书 §3):
- 图谱边(graph_edges):图谱节点 ↔ 对端节点;
- 事件关联(event_chapters):事件 ↔ 章节;
- 大纲树关系:父链/子节点;
- 章节正文引用:章节正文(l4_texts)中提到的 L1 条目名。
实体详情展示复用既有 detail 端点(outline.node_detail 等),本端点只聚合"关联什么、
跳哪里"。抽屉是版块化红线的联动枢纽:面板间靠它互跳,不做硬编码互调。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db import tx

router = APIRouter(prefix="/api/books/{pid}/entity-links", tags=["entity-links"])

ETYPES = ("outline_node", "graph_node", "timeline_event", "l1_entry")


@router.get("")
def entity_links(pid: str, etype: str = Query(...), id: str = Query(...)) -> dict:
    if etype not in ETYPES:
        raise HTTPException(422, f"未知实体类型: {etype}(可选 {'/'.join(ETYPES)})")
    groups: list[dict] = []

    def add(kind: str, items: list[dict]) -> None:
        if items:
            groups.append({"kind": kind, "items": items[:20]})

    with tx() as conn:
        if etype == "outline_node":
            node = conn.execute(
                "SELECT id, parent_id, kind, title FROM outline_nodes"
                " WHERE id=? AND project_id=?", (id, pid)).fetchone()
            if node is None:
                raise HTTPException(404, "大纲节点不存在")
            # 大纲树关系:祖先链(自上而下)+ 直接子节点
            chain: list[dict] = []
            cur = dict(node)
            seen = {id}
            while cur.get("parent_id") and cur["parent_id"] not in seen:
                seen.add(cur["parent_id"])
                parent = conn.execute(
                    "SELECT id, kind, title FROM outline_nodes WHERE id=?",
                    (cur["parent_id"],)).fetchone()
                if parent is None:
                    break
                chain.append(dict(parent))
                cur = dict(parent)
            add("大纲上级", [{**it, "etype": "outline_node"} for it in reversed(chain)])
            add("大纲下级", [{**dict(r), "etype": "outline_node"} for r in conn.execute(
                "SELECT id, kind, title FROM outline_nodes WHERE parent_id=? ORDER BY sort_order",
                (id,)).fetchall()])
            # 事件关联:event_chapters(章 ↔ 事件)
            add("关联事件", [{**dict(r), "etype": "timeline_event"} for r in conn.execute(
                "SELECT e.id, e.title, e.time_label AS extra FROM event_chapters c"
                " JOIN timeline_events e ON e.id = c.event_id"
                " WHERE c.node_id=? ORDER BY e.sort_key", (id,)).fetchall()])
            # 章节正文提到的档案条目(仅章有正文;条目名精确子串匹配,截 20 条)
            l4 = conn.execute(
                "SELECT content FROM l4_texts WHERE node_id=?", (id,)).fetchone()
            if l4 and l4["content"]:
                text = l4["content"]
                mentioned = [dict(r) for r in conn.execute(
                    "SELECT id, name AS title, category AS extra FROM l1_entries"
                    " WHERE project_id=? AND entry_status='confirmed' ORDER BY category, name",
                    (pid,)).fetchall() if r["title"] and r["title"] in text]
                add("正文提到的条目", [{**it, "etype": "l1_entry"} for it in mentioned])
        elif etype == "graph_node":
            node = conn.execute(
                "SELECT id FROM graph_nodes WHERE id=?", (id,)).fetchone()
            if node is None:
                raise HTTPException(404, "图谱节点不存在")
            edges = conn.execute(
                "SELECT * FROM graph_edges WHERE from_node_id=? OR to_node_id=?",
                (id, id)).fetchall()
            items: list[dict] = []
            for e in edges:
                other = e["to_node_id"] if e["from_node_id"] == id else e["from_node_id"]
                peer = conn.execute(
                    "SELECT label FROM graph_nodes WHERE id=?", (other,)).fetchone()
                items.append({
                    "etype": "graph_node", "id": other,
                    "title": peer["label"] if peer else "(已删节点)",
                    "extra": f"{e['kind']}" + (f"·{e['label']}" if e["label"] else ""),
                })
            add("图谱连线", items)
        elif etype == "timeline_event":
            ev = conn.execute(
                "SELECT id FROM timeline_events WHERE id=?", (id,)).fetchone()
            if ev is None:
                raise HTTPException(404, "时间线事件不存在")
            add("关联章节", [{**dict(r), "etype": "outline_node"} for r in conn.execute(
                "SELECT n.id, n.title, n.kind AS extra FROM event_chapters c"
                " JOIN outline_nodes n ON n.id = c.node_id"
                " WHERE c.event_id=? ORDER BY n.sort_order", (id,)).fetchall()])
            add("图谱引用", [{**dict(r), "etype": "graph_node"} for r in conn.execute(
                "SELECT id, label AS title, sub_label AS extra FROM graph_nodes"
                " WHERE ref_type='timeline_event' AND ref_id=?", (id,)).fetchall()])
        else:  # l1_entry
            entry = conn.execute(
                "SELECT id, name FROM l1_entries WHERE id=?", (id,)).fetchone()
            if entry is None:
                raise HTTPException(404, "档案条目不存在")
            add("图谱引用", [{**dict(r), "etype": "graph_node"} for r in conn.execute(
                "SELECT id, label AS title, sub_label AS extra FROM graph_nodes"
                " WHERE ref_type='l1_entry' AND ref_id=?", (id,)).fetchall()])
            if entry["name"]:
                add("正文出现章节", [{**dict(r), "etype": "outline_node"} for r in conn.execute(
                    "SELECT n.id, n.title, n.kind AS extra FROM l4_texts t"
                    " JOIN outline_nodes n ON n.id = t.node_id"
                    " WHERE n.project_id=? AND t.content LIKE ? ORDER BY n.sort_order",
                    (pid, f"%{entry['name']}%")).fetchall()])
    return {"etype": etype, "id": id, "groups": groups}
