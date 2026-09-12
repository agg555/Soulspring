"""批次四③:书=目录工作区 v1——全书结构 md 镜像(执行书 §1③)。

设计约束(池条拍板口径):**DB 为唯一真源,md 是只读镜像**——防双源冲突防重构;
增量策略=整书重建(百章级开销可忽略,原子写防半文件);外部改动收回走既有
文本导入闸门,不做双向实时同步(v2 待拍板)。

目录结构:data/books/<书名>/
  正文/<卷名>/<章名>.md(章直挂总纲归"未分卷")
  设定/<类别中文名>.md(仅 confirmed 条目,提案不镜像)
  大纲.md(树形缩进全文)/ 时间线.md(事件+关联章)
"""
from __future__ import annotations

from pathlib import Path

from .llm.atomic_io import write_text_atomic

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CATEGORY_CN = {
    "worldview": "世界观设定", "character": "人物设定", "power": "力量体系",
    "faction": "势力阵营", "map": "地理设定", "item_economy": "物品经济",
}


def _tree_lines(nodes: list[dict], pid: str) -> list[str]:
    by_parent: dict[str | None, list[dict]] = {}
    for n in nodes:
        by_parent.setdefault(n["parent_id"], []).append(n)
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for n in sorted(by_parent.get(parent, []), key=lambda x: (x["sort_order"], x["id"])):
            mark = {0: "#", 1: "##", 2: "###", 3: "####"}.get(depth, "-")
            head = f"{mark} {n['title']}" if depth <= 3 else f"- {n['title']}"
            if n.get("summary"):
                head += f"\n{n['summary']}"
            lines.append(head)
            walk(n["id"], depth + 1)

    walk(None, 0)
    return lines


def _safe_name(name: str) -> str:
    """书名/卷名/章名→文件系统安全名:去路径分隔符与父目录引用(防穿越,审计式卫生)。"""
    bad = '/\\<>:"|?*'
    cleaned = name.strip()
    for ch in bad:
        cleaned = cleaned.replace(ch, "_")
    cleaned = cleaned.replace("..", "_")
    return cleaned.strip() or "未命名"


def build_mirror(conn, pid: str) -> dict:
    """整书重建镜像;返回 {dir, files}。conn 为已打开事务只读使用。"""
    book = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()
    if book is None:
        raise ValueError("书不存在")
    name = book["name"]
    base = _DATA_DIR / "books" / _safe_name(name)
    files = 0

    def write(rel: str, text: str) -> None:
        nonlocal files
        write_text_atomic(str(base / rel), text)
        files += 1

    # 1) 正文:章按父卷分目录;只镜像有正文的章
    chapters = conn.execute(
        "SELECT n.id, n.title, n.parent_id, t.content FROM outline_nodes n"
        " JOIN l4_texts t ON t.node_id = n.id"
        " WHERE n.project_id=? AND n.kind='chapter' AND TRIM(t.content)<>''",
        (pid,)).fetchall()
    nodes = conn.execute(
        "SELECT id, parent_id, kind, title, summary, sort_order FROM outline_nodes"
        " WHERE project_id=? ORDER BY sort_order, created_at", (pid,)).fetchall()
    title_of = {r["id"]: r["title"] for r in nodes}
    for r in chapters:
        parent = r["parent_id"]
        vol = title_of.get(parent, "未分卷") if parent else "未分卷"
        safe_vol = _safe_name(vol)
        safe_title = _safe_name(r["title"])
        write(f"正文/{safe_vol}/{safe_title}.md",
              f"# {r['title']}\n\n{r['content'].strip()}\n")

    # 2) 大纲.md:树形缩进全文
    tree = "\n".join(_tree_lines([dict(r) for r in nodes], pid)) or "(空大纲)"
    write("大纲.md", f"# {name} · 大纲\n\n{tree}\n")

    # 3) 设定/<类别>.md:confirmed 条目
    entries = conn.execute(
        "SELECT category, name, content FROM l1_entries"
        " WHERE project_id=? AND entry_status='confirmed' ORDER BY category, name",
        (pid,)).fetchall()
    by_cat: dict[str, list] = {}
    for e in entries:
        by_cat.setdefault(e["category"], []).append(e)
    for cat, items in by_cat.items():
        body = "\n\n".join(
            f"## {e['name']}\n\n{(e['content'] or '').strip()}" for e in items)
        write(f"设定/{CATEGORY_CN.get(cat, cat)}.md", f"# {CATEGORY_CN.get(cat, cat)}\n\n{body}\n")

    # 4) 时间线.md:事件+关联章
    events = conn.execute(
        "SELECT title, time_label, line, status, summary FROM timeline_events"
        " WHERE project_id=? ORDER BY sort_key, created_at", (pid,)).fetchall()
    ev_lines = []
    for e in events:
        linked = [r["title"] for r in conn.execute(
            "SELECT n.title FROM event_chapters c JOIN outline_nodes n ON n.id=c.node_id"
            " WHERE c.event_id IN (SELECT id FROM timeline_events WHERE project_id=?"
            " AND title=?)", (pid, e["title"])).fetchall()]
        head = f"- 【{e['time_label'] or '未定时'}】{e['title']}({e['line']}/{e['status']})"
        if linked:
            head += f" → 关联:{'、'.join(linked)}"
        if e["summary"]:
            head += f"\n  {e['summary']}"
        ev_lines.append(head)
    write("时间线.md", f"# {name} · 时间线\n\n" + ("\n".join(ev_lines) or "(无事件)") + "\n")

    return {"dir": str(base), "files": files}
