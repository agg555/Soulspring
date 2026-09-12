"""分层搜索 API(批次七②):FTS5 trigram 子串检索,结果按版块分组。

索引范围与迁移 v17 对齐:章节正文/大纲(title+summary)/档案条目(name+content)/
时间线(title+summary),触发器随写随更(含千章 runner 等旁路进程的直写)。
查询侧分两档:
- q ≥ 3 字符:FTS5 MATCH 短语查询(整体引号包裹防注入语法,子串语义),
  snippet 高亮 + bm25 相关序;
- q 1-2 字符:trigram 物理下限查不到,回退 LIKE 全表兜底(千章体量线性扫
  仍在毫秒级),snippet 手工截取命中上下文。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ..db import tx

router = APIRouter(prefix="/api/search", tags=["search"])

# 分组展示顺序与标签(判据:结果按版块分组)
GROUPS: list[tuple[str, str]] = [
    ("chapter", "章节"),
    ("outline", "大纲"),
    ("entry", "档案条目"),
    ("timeline", "时间线"),
]
_PER_GROUP_LIMIT = 20
_TOTAL_LIMIT = 80


def _fts_phrase(q: str) -> str:
    """用户输入包成 FTS5 短语:内部双引号翻倍,消除语法字符的特殊含义。"""
    return '"' + q.replace('"', '""') + '"'


def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_snippet(content: str, q: str, width: int = 28) -> str:
    pos = content.find(q)
    if pos == -1:
        return content[:width]
    start = max(0, pos - width)
    end = min(len(content), pos + len(q) + width)
    body = content[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{body}{suffix}"


def _search(q: str, pid: str | None) -> list[dict]:
    """查索引,统一产出 {title, group_kind, ref_id, project_id, snippet} 行集。"""
    with tx() as conn:
        if len(q) >= 3:
            match = _fts_phrase(q)
            where, args = ("AND project_id=?" if pid else ""), ([pid] if pid else [])
            rows = conn.execute(
                "SELECT title, group_kind, ref_id, project_id,"
                " snippet(search_index, 1, '「', '」', '…', 28) AS snip"
                f" FROM search_index WHERE search_index MATCH ? {where}"
                " ORDER BY rank LIMIT ?", (match, *args, _TOTAL_LIMIT)).fetchall()
            return [{"title": r["title"], "group_kind": r["group_kind"],
                     "ref_id": r["ref_id"], "project_id": r["project_id"],
                     "snippet": r["snip"] or ""} for r in rows]
        like = f"%{_like_escape(q)}%"
        where, args = ("AND project_id=?" if pid else ""), ([pid] if pid else [])
        rows = conn.execute(
            "SELECT title, group_kind, ref_id, project_id, content"
            " FROM search_index WHERE (title LIKE ? ESCAPE '\\'"
            " OR content LIKE ? ESCAPE '\\')" + where +
            " LIMIT ?", (like, like, *args, _TOTAL_LIMIT)).fetchall()
        return [{"title": r["title"], "group_kind": r["group_kind"],
                 "ref_id": r["ref_id"], "project_id": r["project_id"],
                 "snippet": _like_snippet(r["content"] or "", q)} for r in rows]


@router.get("")
def search(q: str, pid: str | None = None) -> dict:
    """分组搜索:GET /api/search?q=关键词&pid=书id。pid 缺省=跨全书。"""
    query = (q or "").strip()
    empty = [{"group": g, "label": label, "items": []} for g, label in GROUPS]
    if not query:
        return {"q": query, "elapsed_ms": 0, "total": 0, "groups": empty}
    t0 = time.monotonic()
    try:
        rows = _search(query, pid)
    except Exception as exc:  # FTS 查询异常兜底:搜索不可用不该带崩前端
        raise HTTPException(422, f"搜索失败:{str(exc)[:200]}") from exc

    grouped: dict[str, list[dict]] = {g: [] for g, _ in GROUPS}
    for r in rows:
        g = r["group_kind"]
        if g in grouped and len(grouped[g]) < _PER_GROUP_LIMIT:
            grouped[g].append({"ref_id": r["ref_id"],
                               "title": r["title"] or "(无标题)",
                               "snippet": r["snippet"], "project_id": r["project_id"]})
    elapsed = round((time.monotonic() - t0) * 1000, 1)
    groups = [{"group": g, "label": label, "items": grouped[g]} for g, label in GROUPS]
    return {"q": query, "elapsed_ms": elapsed, "total": sum(len(g["items"]) for g in groups),
            "groups": groups}
