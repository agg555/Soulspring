"""算法体检 API(批次三②,2026-09-06 执行书 §2②):六项纯规则检查,零 LLM。

纪要口径:算法体检=免费常驻(本端点),AI 体检=深度可选(既有 book_outline_review)。
全部检查只读现库,不改任何数据、不调模型。检查项(执行书定稿):
  断头章/孤立卷/章密度失衡/伏笔埋设未回收/条目重名/时间线冲突。
"""
from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter

from ..db import tx

router = APIRouter(prefix="/api/books", tags=["diagnostics"])

MAX_CHAPTERS_PER_PARENT = 18          # 章密度失衡阈:单卷/近纲下章数上限(执行书口径)
HOOK_OPEN_STATUSES = ("埋设", "强化")  # 伏笔"未回收"=仍处埋设/强化(回收=闭环)


def _algorithm_check_rows(pid: str) -> list[dict]:
    checks: list[dict] = []

    def _add(key: str, title: str, items: list[dict]) -> None:
        checks.append({"key": key, "title": title, "count": len(items), "items": items})

    with tx() as conn:
        nodes = conn.execute(
            "SELECT id, parent_id, kind, title FROM outline_nodes"
            " WHERE project_id=?", (pid,)).fetchall()
        by_id = {r["id"]: r for r in nodes}

        # 1) 断头章:章无有效归属(无父/父节点缺失/父不是卷或近纲)
        orphans = [
            {"node_id": r["id"], "title": r["title"],
             "detail": "无父节点" if r["parent_id"] is None else
                       (f"父节点缺失({r['parent_id']})" if r["parent_id"] not in by_id
                        else f"父节点类型异常({by_id[r['parent_id']]['kind']})")}
            for r in nodes if r["kind"] == "chapter" and (
                r["parent_id"] is None
                or r["parent_id"] not in by_id
                or by_id[r["parent_id"]]["kind"] not in ("volume", "arc"))
        ]
        _add("orphan_chapter", "断头章(章无有效归属)", orphans)

        # 2)+3) 卷/近纲分组:孤立卷(0 章)与章密度失衡(>18 章)
        parents = [r for r in nodes if r["kind"] in ("volume", "arc")]
        counts = Counter(
            r["parent_id"] for r in nodes
            if r["kind"] == "chapter" and r["parent_id"] in by_id)
        _add("lonely_volume", "孤立卷(下无章)",
             [{"node_id": p["id"], "title": p["title"], "detail": "卷/近纲下没有任何章"}
              for p in parents if counts.get(p["id"], 0) == 0])
        _add("dense_parent", "章密度失衡(下属章过多)",
             [{"node_id": p["id"], "title": p["title"],
               "detail": f"下属 {counts[p['id']]} 章(阈值 {MAX_CHAPTERS_PER_PARENT})"}
              for p in parents if counts.get(p["id"], 0) > MAX_CHAPTERS_PER_PARENT])

        # 4) 伏笔埋设未回收:hook 板节点 style.status ∈ 埋设/强化(回收=闭环)
        hooks = conn.execute(
            "SELECT n.id, n.label, n.style, b.name AS board_name"
            " FROM graph_nodes n JOIN graph_boards b ON b.id = n.board_id"
            " WHERE b.project_id=? AND b.kind='hook'", (pid,)).fetchall()
        open_hooks: list[dict] = []
        for r in hooks:
            try:
                style = json.loads(r["style"] or "{}")
            except (TypeError, ValueError):
                style = {}
            status = str(style.get("status", "埋设"))
            if status in HOOK_OPEN_STATUSES:
                open_hooks.append({"node_id": r["id"], "title": r["label"],
                                   "detail": f"{r['board_name']}·状态 {status}·未见回收"})
        _add("hook_open", "伏笔埋设未回收", open_hooks)

        # 5) 条目重名:同分类下正式条目同名(去首尾空格、大小写不敏感;提案不算)
        rows = conn.execute(
            "SELECT id, category, name FROM l1_entries"
            " WHERE project_id=? AND entry_status='confirmed' ORDER BY category, name",
            (pid,)).fetchall()
        seen: dict[tuple[str, str], str] = {}
        dupes: list[dict] = []
        for r in rows:
            key = (r["category"], r["name"].strip().lower())
            if key in seen:
                dupes.append({"node_id": r["id"], "title": r["name"],
                              "detail": f"与「{seen[key]}」同名(分类 {r['category']})"})
            else:
                seen[key] = r["name"]
        _add("dup_entry", "条目重名(同分类同名)", dupes)

        # 6) 时间线冲突:同线排序键重复(时序不明)+ 事件无任何时间锚(无标签且未关联章)
        events = conn.execute(
            "SELECT id, title, time_label, line, sort_key FROM timeline_events"
            " WHERE project_id=?", (pid,)).fetchall()
        linked = {r["event_id"] for r in conn.execute(
            "SELECT e.event_id AS event_id FROM event_chapters e"
            " JOIN timeline_events t ON t.id = e.event_id WHERE t.project_id=?",
            (pid,)).fetchall()}
        key_seen: dict[tuple[str, int], str] = {}
        conflicts: list[dict] = []
        for r in events:
            key = (r["line"], r["sort_key"])
            if key in key_seen:
                conflicts.append({"node_id": r["id"], "title": r["title"],
                                  "detail": f"与「{key_seen[key]}」同在{r['line']}"
                                            f"且排序键相同(时序不明)"})
            else:
                key_seen[key] = r["title"]
            if not (r["time_label"] or "").strip() and r["id"] not in linked:
                conflicts.append({"node_id": r["id"], "title": r["title"],
                                  "detail": "无时间标签且未关联任何章(缺时间锚)"})
        _add("timeline_conflict", "时间线冲突(排序重复/缺时间锚)", conflicts)

        # 7)+8) 二期③消费者 b:章节信息卡人物数据的新规(数据来自人物板同框边
        # style.at_chapter,与人物关系时间轴同口径;章号取标题「第N章」)
        import re
        char_nodes = conn.execute(
            "SELECT n.ref_id AS ref_id, n.label AS label FROM graph_nodes n"
            " JOIN graph_boards b ON b.id = n.board_id"
            " WHERE b.project_id=? AND b.kind='character'"
            "   AND n.ref_type='l1_entry' AND n.ref_id IS NOT NULL", (pid,)).fetchall()
        char_edges = conn.execute(
            "SELECT n.ref_id AS ref_id,"
            " json_extract(ge.style, '$.at_chapter') AS at_no"
            " FROM graph_edges ge"
            " JOIN graph_boards b ON b.id = ge.board_id"
            " JOIN graph_nodes n ON n.id IN (ge.from_node_id, ge.to_node_id)"
            " WHERE b.project_id=? AND b.kind='character'"
            "   AND n.ref_type='l1_entry' AND n.ref_id IS NOT NULL", (pid,)).fetchall()
        debut: dict[str, int] = {}
        for r in char_edges:
            if r["at_no"] is None:
                continue
            try:
                no = int(r["at_no"])
            except (TypeError, ValueError):
                continue
            if r["ref_id"] not in debut or no < debut[r["ref_id"]]:
                debut[r["ref_id"]] = no
        # 7) 人物未登场先用:档案角色在「第N章」正文出现,但标注登场章更晚
        early: list[dict] = []
        if debut:
            l1_names = {r["id"]: r["name"] for r in conn.execute(
                "SELECT id, name FROM l1_entries"
                " WHERE project_id=? AND entry_status='confirmed' AND category='character'",
                (pid,))}
            chapters_txt = conn.execute(
                "SELECT n.id, n.title, l.content FROM outline_nodes n"
                " JOIN l4_texts l ON l.node_id = n.id"
                " WHERE n.project_id=? AND n.kind='chapter'", (pid,)).fetchall()
            for r in chapters_txt:
                m = re.search(r"第(\d+)章", r["title"] or "")
                if not m or not r["content"]:
                    continue
                no = int(m.group(1))
                for ref_id, name in l1_names.items():
                    if name and name in r["content"] and ref_id in debut \
                            and debut[ref_id] > no:
                        early.append({"node_id": r["id"], "title": r["title"],
                                      "detail": f"「{name}」标注登场为第{debut[ref_id]}章,"
                                                f"本章(第{no}章)已出现"})
        _add("cast_early_use", "人物未登场先用(同框标注晚于正文)", early)
        # 8) 图谱名与档案名不一:人物板节点引用 L1 角色,但标签与档案名不同
        mismatch: list[dict] = []
        seen_ref: set[str] = set()
        for r in char_nodes:
            if not r["ref_id"] or not r["label"] or r["ref_id"] in seen_ref:
                continue
            seen_ref.add(r["ref_id"])
            name = conn.execute("SELECT name FROM l1_entries WHERE id=?",
                                (r["ref_id"],)).fetchone()
            if name and name["name"] != r["label"]:
                mismatch.append({"node_id": r["ref_id"], "title": name["name"],
                                 "detail": f"图谱节点标签「{r['label']}」与档案名不一致"})
        _add("cast_name_mismatch", "图谱名与档案名不一(人物)", mismatch)

        # 9) 一致性升级(候选清单落地批 A):场景人物 vs 同框边对账——章下场景
        #    五字段声明了 characters,但该章同框边(章节卡口径)没有对应人物节点
        import re
        char_labels = {r["label"] for r in conn.execute(
            "SELECT DISTINCT n.label FROM graph_nodes n"
            " JOIN graph_boards b ON b.id = n.board_id"
            " WHERE b.project_id=? AND b.kind='character' AND n.ref_type='l1_entry'",
            (pid,))}
        scenes = conn.execute(
            "SELECT n.id, n.title, n.parent_id, n.scene_fields FROM outline_nodes n"
            " WHERE n.project_id=? AND n.kind='scene'", (pid,)).fetchall()
        mismatch_scene: list[dict] = []
        for s in scenes:
            try:
                sf = json.loads(s["scene_fields"] or "{}")
            except (TypeError, ValueError):
                continue
            declared = [c.strip() for c in (sf.get("characters") or "") if c.strip()]
            if not declared:
                continue
            parent = by_id.get(s["parent_id"])
            if parent is None or parent["kind"] != "chapter":
                continue
            no = re.search(r"第(\d+)章", parent["title"] or "")
            if not no:
                continue
            chapter_no_val = int(no.group(1))
            cast_here = set()
            edges = conn.execute(
                "SELECT e.from_node_id, e.to_node_id FROM graph_edges e"
                " JOIN graph_boards b ON b.id = e.board_id"
                " WHERE b.project_id=? AND b.kind='character'"
                " AND e.kind='同框' AND json_extract(e.style, '$.at_chapter')=?",
                (pid, chapter_no_val)).fetchall()
            for e in edges:
                for nid in (e["from_node_id"], e["to_node_id"]):
                    lbl = conn.execute(
                        "SELECT label FROM graph_nodes WHERE id=?", (nid,)).fetchone()
                    if lbl:
                        cast_here.add(lbl["label"])
            ghost = [c for c in declared
                     if c not in cast_here and c in char_labels]
            if ghost:
                mismatch_scene.append({
                    "node_id": s["id"], "title": parent["title"],
                    "detail": f"场景「{s['title']}」声明人物 {ghost},"
                              f"但本章同框边没有他们(章节卡与场景卡不一致)"})
        _add("cast_scene_mismatch", "场景人物与同框边不一致", mismatch_scene)

    return checks


@router.get("/{pid}/algorithm-check")
def algorithm_check(pid: str) -> dict:
    checks = _algorithm_check_rows(pid)
    return {"project_id": pid,
            "total_issues": sum(c["count"] for c in checks),
            "checks": checks}


@router.get("/{pid}/graph-overview")
def graph_overview(pid: str) -> dict:
    """批次三⑥总览图谱:聚合全部板的节点/边(只读)。

    数据与单板同源=单板任何调整,总览重新拉取即自动同步,无需额外同步逻辑;
    象限布局偏移由前端按板序计算,后端只出原始数据。"""
    with tx() as conn:
        boards = conn.execute(
            "SELECT id, kind, name FROM graph_boards WHERE project_id=?"
            " ORDER BY created_at, id", (pid,)).fetchall()
        out: list[dict] = []
        for b in boards:
            nodes = [dict(r) for r in conn.execute(
                "SELECT id, label, ref_type, ref_id, x, y, style FROM graph_nodes"
                " WHERE board_id=? ORDER BY created_at, id", (b["id"],)).fetchall()]
            edges = [dict(r) for r in conn.execute(
                "SELECT id, from_node_id, to_node_id, label, kind FROM graph_edges"
                " WHERE board_id=?", (b["id"],)).fetchall()]
            # 类别派生与单板 board_detail 同源(graphs.py):l1 来源带 L1 类别,事件/自由单列
            ref_ids = [n["ref_id"] for n in nodes
                       if n["ref_type"] == "l1_entry" and n["ref_id"]]
            cats: dict[str, str] = {}
            if ref_ids:
                marks = ",".join("?" * len(ref_ids))
                cats = {r["id"]: r["category"] for r in conn.execute(
                    f"SELECT id, category FROM l1_entries WHERE id IN ({marks})",
                    ref_ids).fetchall()}
            for n in nodes:
                n["style"] = json.loads(n.get("style") or "{}")
                n["category"] = cats.get(n["ref_id"] or "") if n["ref_type"] == "l1_entry" else (
                    "timeline_event" if n["ref_type"] == "timeline_event" else "free")
            out.append({"board_id": b["id"], "kind": b["kind"], "name": b["name"],
                        "nodes": nodes, "edges": edges})
    return {"project_id": pid, "boards": out, "board_count": len(out),
            "node_count": sum(len(b["nodes"]) for b in out),
            "edge_count": sum(len(b["edges"]) for b in out)}
