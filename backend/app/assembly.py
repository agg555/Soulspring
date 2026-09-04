"""装配引擎(F4):写第 N 章前从各层选择性提取,装配清单落日志。

装配协议落地(任务书 §4.2):
- 档案层取本章相关切片(L1 条目带"常驻/按需"人工标记,按需条目按计划卡匹配);
- 状态层取全量真相文件(L2 官方区);
- 进度层取近纲窗口(本章的祖先链 + 相邻章);
- 上限可配置(设置页 assembly.token_limit,默认 6000 字符),超限先裁按需条目;
- 每次装配落 assembly_logs(日志五件套之一)。
"""
from __future__ import annotations

import json
import uuid

from .audit.world_state import L2_TYPES
from .common import _now
from .db import tx
from .settings_store import get_settings

OUTLINE_KIND_LABEL = {"category": "总纲", "volume": "卷", "arc": "近纲", "chapter": "章", "scene": "场景"}


def _get_node(conn, pid: str, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM outline_nodes WHERE id=? AND project_id=?", (node_id, pid)).fetchone()
    return dict(row) if row else None


def _ancestry(conn, node: dict) -> list[dict]:
    """从根到本章的祖先链。"""
    chain = []
    cur = node
    while cur:
        chain.append(cur)
        parent_id = cur.get("parent_id")
        cur = dict(conn.execute(
            "SELECT * FROM outline_nodes WHERE id=?", (parent_id,)).fetchone()) if parent_id else None
    return list(reversed(chain))


def _nearby_chapters(conn, node: dict, window: int = 1) -> list[dict]:
    """同近纲下本章前后各 window 章的标题与状态。"""
    rows = conn.execute(
        "SELECT id, title, status FROM outline_nodes WHERE parent_id=? AND kind='chapter'"
        " ORDER BY sort_order", (node["parent_id"],)).fetchall()
    chapters = [dict(r) for r in rows]
    idx = next((i for i, c in enumerate(chapters) if c["id"] == node["id"]), None)
    if idx is None:
        return []
    lo, hi = max(0, idx - window), min(len(chapters), idx + window + 1)
    return chapters[lo:hi]


def build_assembly(project_id: str, node_id: str, *, log: bool = True,
                   extra_sections: list[dict] | None = None) -> dict:
    """构建装配体;不写库时可用 log=False 预览。

    extra_sections:外部注入段(生成时选用的技能正文),计总字符、随日志留痕、进 prompt。
    """
    limit = int(get_settings()["assembly"].get("token_limit") or 6000)

    with tx() as conn:
        node = _get_node(conn, project_id, node_id)
        if node is None:
            raise ValueError("章节点不存在")
        if node["kind"] != "chapter":
            raise ValueError("只有章节点可以装配")

        sections: list[dict] = []
        chain = _ancestry(conn, node)
        outline_lines = [f"{OUTLINE_KIND_LABEL[n['kind']]}:{n['title']}" for n in chain]
        nearby = _nearby_chapters(conn, node)
        if nearby:
            outline_lines.append("相邻章:" + ";".join(
                f"{c['title']}({c['status']})" for c in nearby))
        plan_row = conn.execute(
            "SELECT plan FROM chapter_plans WHERE node_id=?", (node_id,)).fetchone()
        plan = json.loads(plan_row["plan"]) if plan_row else {}
        if plan:
            outline_lines.append("计划卡:" + json.dumps(plan, ensure_ascii=False))
        sections.append({"source": "outline", "kind": "always", "title": "近纲窗口",
                         "content": "\n".join(outline_lines), "included": True})

        # L2 全量真相文件(官方区)
        rows = conn.execute(
            "SELECT file_type, content FROM l2_files WHERE project_id=? AND status='official'"
            " ORDER BY file_type", (project_id,)).fetchall()
        blobs = {r["file_type"]: r["content"] for r in rows}
        for ft in L2_TYPES:
            content = (blobs.get(ft) or "").strip() or "(空)"
            sections.append({"source": f"l2:{ft}", "kind": "always", "title": ft,
                             "content": content, "included": True})

        # L1:常驻全部,按需按计划卡文本匹配
        entries = conn.execute(
            "SELECT id, category, name, content, presence FROM l1_entries"
            " WHERE project_id=? AND entry_status='confirmed' ORDER BY category, name",
            (project_id,)).fetchall()
        plan_text = json.dumps(plan, ensure_ascii=False)
        for e in entries:
            on_demand = e["presence"] != "always"
            matched = (not plan) or (e["name"] in plan_text)
            included = (not on_demand) or matched
            sections.append({
                "source": f"l1:{e['category']}", "kind": "always" if not on_demand else "on_demand",
                "title": e["name"], "content": e["content"], "included": included,
                "entry_id": e["id"],
            })

    # 外部注入段(需求2:生成处选技能 → 技能正文随装配体进 prompt 并随日志留痕)
    for s in (extra_sections or []):
        sections.append({**s, "included": True})

    # 上限控制:超限先排除按需条目,再不动常驻/L2(超限事实记录在案)
    total = sum(len(s["content"]) for s in sections if s["included"])
    trimmed = False
    for s in sections:
        if total <= limit:
            break
        if s["kind"] == "on_demand" and s["included"]:
            s["included"] = False
            s["trimmed_by_limit"] = True
            trimmed = True
            total = sum(len(x["content"]) for x in sections if x["included"])

    result = {
        "node_id": node_id,
        "sections": sections,
        "total_chars": total,
        "limit_chars": limit,
        "over_limit": total > limit,
        "trimmed": trimmed,
        "plan": plan,
    }

    if log:
        with tx() as conn:
            conn.execute(
                "INSERT INTO assembly_logs(id, project_id, node_id, plan, sections,"
                " total_chars, limit_chars, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"asm_{uuid.uuid4().hex[:20]}", project_id, node_id,
                 json.dumps(plan, ensure_ascii=False),
                 json.dumps(sections, ensure_ascii=False),
                 total, limit, _now()))
    return result


def assembled_text(assembly: dict) -> str:
    """把装配体拼成喂模型的文本(仅 included 段)。"""
    parts = []
    for s in assembly["sections"]:
        if s["included"]:
            parts.append(f"## {s['title']}\n{s['content']}")
    return "\n\n".join(parts)


def build_node_context(project_id: str, node_id: str, limit: int | None = None) -> str:
    """节点级上下文(C3,大纲节点对话用):祖先链 + 本节点字段 + L1 常驻条目。

    与 build_assembly 的差异:面向任意节点(不要求章),不取 L2 真相文件全文、
    不落装配日志(对话高频,零 token 上下文不值得一条日志);上限裁剪先砍 L1。
    """
    limit = limit or int(get_settings()["assembly"].get("token_limit") or 6000)
    with tx() as conn:
        node = _get_node(conn, project_id, node_id)
        if node is None:
            raise ValueError("节点不存在")
        chain = _ancestry(conn, node)
        lines = [f"{OUTLINE_KIND_LABEL.get(n['kind'], n['kind'])}:{n['title']}" for n in chain]
        sections = [{"kind": "always", "title": "大纲位置(祖先链)",
                     "content": "\n".join(lines)}]
        self_bits = [f"节点类型:{OUTLINE_KIND_LABEL.get(node['kind'], node['kind'])}",
                     f"标题:{node['title']}"]
        if node.get("summary"):
            self_bits.append(f"摘要:{node['summary']}")
        if node.get("note"):
            self_bits.append(f"备注:{node['note']}")
        if node["kind"] == "scene":
            try:
                sf = json.loads(node.get("scene_fields") or "{}")
            except json.JSONDecodeError:
                sf = {}
            if sf:
                self_bits.append("场景五字段:" + json.dumps(sf, ensure_ascii=False))
        children = conn.execute(
            "SELECT kind, title FROM outline_nodes WHERE parent_id=? ORDER BY sort_order",
            (node_id,)).fetchall()
        if children:
            self_bits.append("子节点:" + ";".join(
                f"{OUTLINE_KIND_LABEL.get(c['kind'], c['kind'])}·{c['title']}" for c in children))
        sections.append({"kind": "always", "title": "本节点",
                         "content": "\n".join(self_bits)})
        for e in conn.execute(
                "SELECT category, name, content FROM l1_entries"
                " WHERE project_id=? AND entry_status='confirmed' AND presence='always'"
                " ORDER BY category, name", (project_id,)).fetchall():
            sections.append({"kind": "on_demand", "title": f"L1·{e['name']}",
                             "content": f"({e['category']}) {e['content']}"})
    total = sum(len(s["content"]) for s in sections)
    for s in sections:   # 超限先砍 L1 条目(keep 大纲位置与本节点)
        if total <= limit:
            break
        if s["kind"] == "on_demand":
            total -= len(s["content"])
            s["included"] = False
    for s in sections:
        s.setdefault("included", True)
    return "\n\n".join(f"## {s['title']}\n{s['content']}" for s in sections if s["included"])


def save_chapter_plan(node_id: str, plan: dict) -> None:
    now = _now()
    with tx() as conn:
        conn.execute(
            "INSERT INTO chapter_plans(node_id, plan, updated_at) VALUES(?,?,?)"
            " ON CONFLICT(node_id) DO UPDATE SET plan=excluded.plan, updated_at=excluded.updated_at",
            (node_id, json.dumps(plan, ensure_ascii=False), now))


def get_chapter_plan(node_id: str) -> dict:
    with tx() as conn:
        row = conn.execute("SELECT plan FROM chapter_plans WHERE node_id=?", (node_id,)).fetchone()
    return json.loads(row["plan"]) if row else {}


def build_book_context(project_id: str, limit: int | None = None) -> str:
    """书级上下文(书工作区中央"书级对话",骨架批 2026-09-04,执行书 §2):
    书信息 + 大纲概要(树形标题链,节点带 id 供 outline_field 建议引用原值)
    + 近期章节状态 + L1 常驻条目摘要。裁剪同 build_node_context:超限先砍 L1 段,
    守 assembly.token_limit(默认 6000)上限。
    """
    limit = limit or int(get_settings()["assembly"].get("token_limit") or 6000)
    with tx() as conn:
        sections: list[dict] = []

        book = conn.execute(
            "SELECT name, genre, description FROM projects WHERE id=?", (project_id,)).fetchone()
        bits: list[str] = []
        if book is not None:
            bits.append(f"书名:{book['name']}")
            if book["genre"]:
                bits.append(f"类型:{book['genre']}")
            if book["description"]:
                bits.append(f"简介:{book['description']}")
        sections.append({"kind": "always", "title": "本书信息", "content": "\n".join(bits)})

        # 大纲概要:树形标题链(缩进 + 状态 + node_id 原文,建议引用必须用 id 原文)
        lines: list[str] = []

        def _walk(parent_id: str | None, depth: int) -> None:
            rows = conn.execute(
                "SELECT id, kind, title, status FROM outline_nodes WHERE project_id=?"
                " AND parent_id IS ? ORDER BY sort_order", (project_id, parent_id)).fetchall()
            for r in rows:
                lines.append("  " * depth
                             + f"{OUTLINE_KIND_LABEL.get(r['kind'], r['kind'])}·{r['title']}"
                               f"[{r['status']}] (node_id=`{r['id']}`)")
                _walk(r["id"], depth + 1)

        _walk(None, 0)
        sections.append({"kind": "always", "title": "大纲概要(树形标题链)",
                         "content": "\n".join(lines) or "(大纲还是空的)"})

        # 近期章节状态:最近状态变动的 8 章(含字数,读 l4 正文长度)
        recent = conn.execute(
            "SELECT n.id, n.title, n.status, n.status_changed_at,"
            " (SELECT LENGTH(content) FROM l4_texts t WHERE t.node_id = n.id) AS chars"
            " FROM outline_nodes n WHERE n.project_id=? AND n.kind='chapter'"
            " AND n.status_changed_at IS NOT NULL"
            " ORDER BY n.status_changed_at DESC LIMIT 8", (project_id,)).fetchall()
        if recent:
            rlines = [f"{r['title']}[{r['status']}]"
                      f"{f' {r['chars']} 字' if r['chars'] else ''}"
                      f"({r['status_changed_at'] or ''})" for r in recent]
            sections.append({"kind": "always", "title": "近期章节状态",
                             "content": "\n".join(rlines)})

        # L1 常驻条目摘要(条目内容截 400 字,超限整段先砍)
        for e in conn.execute(
                "SELECT category, name, content FROM l1_entries"
                " WHERE project_id=? AND entry_status='confirmed' AND presence='always'"
                " ORDER BY category, name", (project_id,)).fetchall():
            body_text = e["content"] or ""
            if len(body_text) > 400:
                body_text = body_text[:400] + "…(摘要截断,全文见档案库)"
            sections.append({"kind": "on_demand", "title": f"L1·{e['name']}",
                             "content": f"({e['category']}) {body_text}"})

    total = sum(len(s["content"]) for s in sections)
    for s in sections:   # 超限先砍 L1 摘要段(keep 书信息/大纲概要/近期章节)
        if total <= limit:
            break
        if s["kind"] == "on_demand":
            total -= len(s["content"])
            s["included"] = False
    for s in sections:
        s.setdefault("included", True)
    return "\n\n".join(f"## {s['title']}\n{s['content']}" for s in sections if s["included"])
