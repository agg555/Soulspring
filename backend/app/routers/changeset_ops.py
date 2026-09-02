"""变更集与代码审计操作(S2 拆自 workbench.py,纯移动零行为变化)。

节点查询(_get_node)/双层代码审计(_code_audit)/人工豁免延续
(_dismiss_key/_carry_dismissals)/变更集读写(_open_changeset/_changeset_view/
_put_patch)。workbench 路由与 adopt(对话建议采纳)共同依赖本模块。
"""
from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import HTTPException

from ..audit.anti_ai import analyze_text, generate_learning_examples
from ..audit.code_checks import CodeChecker
from ..audit.world_state import load_world_state
from ..common import _now
from ..db import tx


def _get_node(pid: str, nid: str) -> dict:
    with tx() as conn:
        row = conn.execute(
            "SELECT * FROM outline_nodes WHERE id=? AND project_id=?", (nid, pid)).fetchone()
    if row is None:
        raise HTTPException(404, "章节点不存在")
    node = dict(row)
    if node["kind"] != "chapter":
        raise HTTPException(422, "只有章节点可以进入写章工作台")
    return node


def _recent_chapter_texts(pid: str, limit: int = 3) -> list[str]:
    """取本项目近期章节正文,供跨章意象重复检测(去 AI 味信号之一)。"""
    with tx() as conn:
        rows = conn.execute(
            "SELECT t.content FROM l4_texts t"
            " JOIN outline_nodes n ON n.id = t.node_id"
            " WHERE n.project_id = ? AND n.kind = 'chapter'"
            " ORDER BY n.sort_order DESC, n.updated_at DESC LIMIT ?",
            (pid, limit)).fetchall()
    return [r["content"] or "" for r in rows]


def _code_audit(pid: str, node: dict, text: str) -> tuple[dict, dict]:
    """跑代码层审计 + anti_ai + 去 AI 味质量信号,返回 (validations, summary)。"""
    chapter_number = _chapter_index(pid, node)
    ws = load_world_state(pid)
    code = CodeChecker().check_all(text, ws, chapter_number, _recent_chapter_texts(pid))
    anti = analyze_text(text)
    examples = generate_learning_examples(anti, text)

    validations = []
    for i in code.issues:
        validations.append({
            "code": i.category,
            "status": "failed" if i.severity == "critical" else "warning",
            "message": i.description,
            "dimension": i.dimension,
            "suggestion": i.suggestion,
            "auto_fixable": i.auto_fixable,
            "evidence": i.evidence,
        })
    review_summary = {
        "code": code.to_dict(),
        "anti_ai": {**{k: v for k, v in anti.items() if k != "fatigue_words"},
                    "fatigue_words": anti["fatigue_words"][:8]},
        "learning_examples": examples[:6],
    }
    return validations, review_summary


def _chapter_index(pid: str, node: dict) -> int:
    """章在全书中的序号(创建先后);用于伏笔龄期等。"""
    with tx() as conn:
        row = conn.execute(
            "SELECT COUNT(*)+1 AS n FROM outline_nodes WHERE project_id=? AND kind='chapter'"
            " AND rowid <= (SELECT rowid FROM outline_nodes WHERE id=?)",
            (pid, node["id"])).fetchone()
    return row["n"] if row else 1


def _dismiss_key(v: dict) -> str:
    """豁免匹配键:类别 + 消息模板哈希;刻意不含 evidence。

    evidence 是 ±100 字上下文窗口(code_checks.py),正文任何增删都会改变它——
    用它做键曾导致"人改保存后豁免丢失、critical 复活卡合入"(2026-08-31 实测)。
    message 为审计器的模板化文案,重审计间稳定;同 message 的问题视为同一误报判定。
    """
    raw = v.get("code", "") + "|" + v.get("message", "")
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _carry_dismissals(new_validations: list, old_validations: list) -> None:
    """重审计后延续人工豁免:同键问题继承 dismissed 标记。"""
    dismissed = {_dismiss_key(v): v.get("dismiss_note", "") for v in old_validations if v.get("dismissed")}
    for v in new_validations:
        key = _dismiss_key(v)
        if key in dismissed:
            v["dismissed"] = True
            v["dismiss_note"] = dismissed[key]


def _open_changeset(nid: str) -> dict | None:
    with tx() as conn:
        row = conn.execute(
            "SELECT * FROM changesets WHERE node_id=? AND status IN ('draft','approved')"
            " ORDER BY created_at DESC LIMIT 1", (nid,)).fetchone()
    return dict(row) if row else None


def _changeset_view(cs: dict) -> dict:
    with tx() as conn:
        history = [dict(r) for r in conn.execute(
            "SELECT * FROM changeset_patches WHERE changeset_id=? ORDER BY version",
            (cs["id"],)).fetchall()]
        node = conn.execute("SELECT status FROM outline_nodes WHERE id=?",
                            (cs["node_id"],)).fetchone()
    # C5 版本历史:patches 语义不变(每个 field 的当前版本 = 最高版本号),
    # 全部历史版本进 patch_history 供对比/回滚;旧调用方零改动。
    current: dict[str, dict] = {}
    for p in history:
        current[p["field"]] = p
    return {
        "id": cs["id"], "node_id": cs["node_id"], "status": cs["status"],
        "validations": json.loads(cs.get("validations") or "[]"),
        "review": json.loads(cs["review"]) if cs.get("review") else None,
        "task_spec": json.loads(cs["task_spec"]) if cs.get("task_spec") else None,
        "patches": list(current.values()),
        "patch_history": history,
        "node_status": node["status"] if node else None,
        "created_at": cs["created_at"], "updated_at": cs.get("updated_at"),
    }


def _put_patch(conn, cs_id: str, node_id: str, after: str, reason: str,
               expected_revision: int | None, source: str | None = None,
               project_id: str | None = None):
    """追加式写入补丁(C5 版本历史):旧版本一律保留,version 递增,不覆盖不删行。

    解决重 roll 覆盖丢档;回滚 = 以历史文本为 after 再追加一个新版本,版本链完整。
    before 语义不变:写入时刻的正式正文(l4_texts),供乐观锁与 diff 基线用。

    码字埋点(第三批 B1):source='human'(人改保存)|'ai'(草稿/自修/对话正文采纳)
    时记 word_count_log,delta = 相对上一版草稿的字数差(负=删,算净增);
    source=None(回滚)不记——内容来自历史版本,不是新产量;合入(apply)不记——
    合入只是把 patch.after 落 l4,不再算一次产量。
    """
    before = ""
    row = conn.execute("SELECT content FROM l4_texts WHERE node_id=?", (node_id,)).fetchone()
    if row:
        before = row["content"]
    before_hash = hashlib.sha1(before.encode()).hexdigest()[:12]
    ver = conn.execute(
        "SELECT COALESCE(MAX(version),0)+1 AS v FROM changeset_patches"
        " WHERE changeset_id=?", (cs_id,)).fetchone()["v"]
    conn.execute(
        "INSERT INTO changeset_patches(id, changeset_id, target_type, target_id, field,"
        " before_hash, expected_revision, before, after, reason, selected, version, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)",
        (f"patch_{uuid.uuid4().hex[:20]}", cs_id, "chapter", node_id, "content",
         before_hash, expected_revision, before, after, reason, ver, _now()))
    if source:
        prev = conn.execute(
            "SELECT length(after) AS n FROM changeset_patches WHERE changeset_id=?"
            " AND field='content' AND version < ? ORDER BY version DESC LIMIT 1",
            (cs_id, ver)).fetchone()
        prev_len = prev["n"] or 0 if prev else 0
        if project_id is None:
            cs_row = conn.execute(
                "SELECT project_id FROM changesets WHERE id=?", (cs_id,)).fetchone()
            project_id = cs_row["project_id"] if cs_row else None
        conn.execute(
            "INSERT INTO word_count_log(id, project_id, node_id, source, delta,"
            " words_after, created_at) VALUES(?,?,?,?,?,?,?)",
            (f"wc_{uuid.uuid4().hex[:20]}", project_id, node_id, source,
             len(after) - prev_len, len(after), _now()))
