"""驾驶舱与创作面板 API(第三批,任务词 2026-09-01)。

- B1 全书驾驶舱:每章一行(状态/字数/审计/评审/朱雀/成本/最近阶段),纯聚合读;
- B2 单章生产时间线:装配→草稿→审计→人改→终审的工程调用链,数据全来自现成日志表;
- B4 分值合成:加讳和分,critical 一票否决仅展示,权重存 settings.dashboard 可调,
  只展示留痕,不改任何既有闸门;
- 码字统计:word_count_log 聚合(人工才叫码字,AI 分列);
- 剧情时间线(timeline_events + event_chapters):人可 CRUD,AI 改动走建议协议轻档确认;
- 角色关系图(character_relations)只读:写端点已下线(审计 S10,2026-09-01),
  关系维护走统一图谱引擎(graphs.py),旧表冻结作对照(v11 迁移)。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..common import _now
from ..db import tx
from ..settings_store import get_settings
from .outline import STATUS_LABELS

router = APIRouter(prefix="/api", tags=["dashboard"])

REVIEW_KIND_LABEL = {"category": "总纲", "volume": "卷", "arc": "近纲",
                     "chapter": "章", "scene": "场景"}


def _json_load(text: str | None, default):
    try:
        return json.loads(text) if text else default
    except json.JSONDecodeError:
        return default


# ── B1/B4 全书驾驶舱 ──

def _quality_parts(row: dict, alert: float) -> dict:
    """B4 分量(各自归一到 0-10;critical 一票否决单独标记)。"""
    review = row.get("review") or {}
    scores = [v.get("score", 0) for v in (review.get("scores") or {}).values()]
    review_score = round(sum(scores) / len(scores), 2) if scores else None
    zhuque = row.get("zhuque_human")            # 0-100
    cost = row.get("cost") or 0.0
    cost_score = round(max(0.0, min(10.0, 10 * (1 - cost / alert))), 2) if alert > 0 else 10.0
    return {
        "review_score": review_score,        # 0-10,None=未评审
        "zhuque_score": round(zhuque / 10, 2) if zhuque is not None else None,
        "cost": cost,
        "cost_score": cost_score,
        "critical": row.get("critical", 0),  # >0 = 一票否决(展示层)
    }


@router.get("/books/{pid}/dashboard")
def book_dashboard(pid: str) -> dict:
    cfg = get_settings()["dashboard"]
    alert = float(get_settings()["budget"].get("per_chapter_alert") or 0.25)
    with tx() as conn:
        chapters = conn.execute(
            "SELECT id, title, status, sort_order FROM outline_nodes"
            " WHERE project_id=? AND kind='chapter' ORDER BY sort_order", (pid,)).fetchall()
        # 二期①五面审计修复(2026-09-09):原实现每章 6 条独立查询(千章书=6204 条
        # SQL,书况台 37.5s)。改为 6 条批量查询+Python 聚合,输出行形状分毫不变。
        nids = [c["id"] for c in chapters]
        marks = ",".join("?" * len(nids)) if nids else "NULL"
        l4_len = {r["node_id"]: (r["n"] or 0) for r in conn.execute(
            f"SELECT node_id, LENGTH(content) AS n FROM l4_texts WHERE node_id IN ({marks})",
            nids)}
        # 每章最新补丁字数(无 l4 时兜底):按 version 最大取
        patch_len: dict[str, int] = {}
        for r in conn.execute(
                "SELECT c.node_id AS node_id, p.after AS after FROM changeset_patches p"
                " JOIN changesets c ON c.id = p.changeset_id"
                " WHERE c.node_id IN (" + marks + ") AND p.field='content'"
                " ORDER BY c.node_id, p.version", nids):
            patch_len[r["node_id"]] = len(r["after"]) if r["after"] else 0   # 后版本覆盖前
        cs_latest: dict[str, dict] = {}
        for r in conn.execute(
                "SELECT node_id, validations, review FROM changesets"
                " WHERE node_id IN (" + marks + ") AND status IN ('draft','applied','approved')"
                " ORDER BY created_at", nids):
            cs_latest[r["node_id"]] = dict(r)   # 后创建覆盖先创建=每章最新一条
        zq_latest = {r["node_id"]: r["human_ratio"] for r in conn.execute(
            f"SELECT node_id, human_ratio FROM zhuque_log WHERE node_id IN ({marks})"
            " ORDER BY created_at", nids)}       # 后写覆盖=每章最新
        stage_latest: dict[str, dict] = {}
        for r in conn.execute(
                "SELECT node_id, stage, updated_at FROM gen_tasks"
                f" WHERE node_id IN ({marks}) ORDER BY created_at", nids):
            stage_latest[r["node_id"]] = dict(r)
        cost_by_node = {r["node_id"]: round(r["c"] or 0, 4) for r in conn.execute(
            "SELECT r.node_id AS node_id, SUM(u.cost_total) AS c FROM ai_usage_logs u"
            " JOIN agent_runs r ON r.id = u.run_id"
            " WHERE r.project_id=? GROUP BY r.node_id", (pid,))}
        rows_out = []
        for ch in chapters:
            nid = ch["id"]
            words = l4_len.get(nid) or patch_len.get(nid, 0)
            cs = cs_latest.get(nid)
            validations = _json_load(cs["validations"] if cs else None, [])
            critical = sum(1 for v in validations
                           if v.get("status") == "failed" and not v.get("dismissed"))
            warning = sum(1 for v in validations
                          if v.get("status") == "warning" and not v.get("dismissed"))
            stage = stage_latest.get(nid)
            row = {
                "node_id": nid, "title": ch["title"], "status": ch["status"],
                "status_label": STATUS_LABELS.get(ch["status"], ch["status"]),
                "words": words,
                "critical": critical, "warning": warning,
                "review": _json_load(cs["review"] if cs else None, None),
                "zhuque_human": (zq_latest[nid] * 100)
                    if nid in zq_latest and zq_latest[nid] is not None else None,
                "cost": cost_by_node.get(nid, 0.0),
                "last_stage": stage["stage"] if stage else None,
                "last_stage_at": stage["updated_at"] if stage else None,
            }
            parts = _quality_parts(row, alert)
            w_sum = (cfg["w_review"] + cfg["w_zhuque"] + cfg["w_cost"]) or 1.0
            parts_vals = [parts["review_score"], parts["zhuque_score"], parts["cost_score"]]
            if parts["critical"] > 0:
                parts["score"] = None
                parts["veto"] = True
            elif all(v is None for v in parts_vals[:2]):
                parts["score"] = None      # 无评审无朱雀:分值不合成
                parts["veto"] = False
            else:
                parts["score"] = round(sum(
                    (v or 0) * w for v, w in zip(
                        parts_vals, (cfg["w_review"], cfg["w_zhuque"], cfg["w_cost"]))) / w_sum, 2)
                parts["veto"] = False
            row["quality"] = parts
            rows_out.append(row)
    return {
        "chapters": rows_out,
        "weights": dict(cfg),
        "alert": alert,
        "status_labels": STATUS_LABELS,
    }


class WeightsIn(BaseModel):
    w_review: float | None = None
    w_zhuque: float | None = None
    w_cost: float | None = None


@router.put("/books/{pid}/dashboard/weights")
def put_dashboard_weights(pid: str, body: WeightsIn) -> dict:
    from ..settings_store import update_settings
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if patch and (min(patch.values()) < 0 or max(patch.values()) > 10):
        raise HTTPException(422, "权重取值 0-10")
    if patch:
        update_settings("dashboard", patch)
    return {"ok": True, "weights": dict(get_settings()["dashboard"])}


# ── B2 单章生产时间线(工程调用链,聚合现成日志表)──

@router.get("/workbench/{nid}/production-timeline")
def production_timeline(nid: str, project_id: str) -> dict:
    with tx() as conn:
        node = conn.execute(
            "SELECT title, status FROM outline_nodes WHERE id=?", (nid,)).fetchone()
        if node is None:
            raise HTTPException(404, "章节点不存在")
        node = dict(node)
        node["status_label"] = STATUS_LABELS.get(node["status"], node["status"])
        events: list[dict] = []

        for r in conn.execute(
                "SELECT total_chars, limit_chars, created_at FROM assembly_logs"
                " WHERE node_id=? ORDER BY created_at", (nid,)).fetchall():
            events.append({"kind": "装配", "at": r["created_at"],
                           "detail": f"装配 {r['total_chars']}/{r['limit_chars']} 字符"})
        for r in conn.execute(
                "SELECT kind, stage, status, skill, usage_total, created_at, updated_at"
                " FROM gen_tasks WHERE node_id=? ORDER BY created_at", (nid,)).fetchall():
            events.append({
                "kind": "草稿任务" if r["kind"] == "draft" else "AI 自修",
                "at": r["created_at"], "ended_at": r["updated_at"],
                "detail": f"阶段 {r['stage']} · {r['status']}"
                          + (f" · 技能 {r['skill']}" if r["skill"] else "")
                          + (f" · ¥{r['usage_total']}" if r["usage_total"] else "")})
        for r in conn.execute(
                "SELECT p.reason, p.version, length(p.after) AS n,"
                " COALESCE(p.created_at, '') AS created_at"
                " FROM changeset_patches p JOIN changesets c ON c.id=p.changeset_id"
                " WHERE c.node_id=? ORDER BY p.created_at", (nid,)).fetchall():
            events.append({"kind": f"补丁 v{r['version']}", "at": r["created_at"],
                           "detail": f"{r['reason']} · {r['n']} 字"})
        for r in conn.execute(
                "SELECT from_status, to_status, changed_at, note FROM l3_status_log"
                " WHERE node_id=? ORDER BY changed_at", (nid,)).fetchall():
            events.append({"kind": "状态", "at": r["changed_at"],
                           "detail": f"{r['from_status'] or '—'} → {r['to_status']}"
                                     + (f"({r['note']})" if r["note"] else "")})
        for r in conn.execute(
                "SELECT verdict, human_ratio, created_at FROM zhuque_log"
                " WHERE node_id=? ORDER BY created_at", (nid,)).fetchall():
            events.append({"kind": "朱雀", "at": r["created_at"],
                           "detail": f"{r['verdict']}"
                                     + (f" · 人工 {round(r['human_ratio']*100)}%" if r["human_ratio"] is not None else "")})
    # 旧补丁行(v8 加列前)created_at 可能为 NULL,排序兜底空串置顶
    events.sort(key=lambda e: e["at"] or "")
    return {"node": dict(node), "events": events}


# ── 码字统计(B:人工才叫码字,AI 分列)──

@router.get("/books/{pid}/word-stats")
@router.get("/word-stats")   # 总览卡用:pid 可空 = 全书合计
def word_stats(pid: str = "", node_id: str = "", since: str = "") -> dict:
    """since:码字计时器用——该时刻起的人工增量聚合(第四批 E)。

    口径注(审计 E区):chapter 聚合只在 node_id 非空时有值;pid 为空(全书合计)时
    chapter 恒空——跨书无法定位"该章",属预期行为,总览卡不消费该字段。
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    hour_start = (now - timedelta(hours=1)).isoformat()

    def conds(extra: str = "", *extra_params) -> tuple[str, tuple]:
        # pid 可空 = 全项目聚合(总览卡);有 pid 按书;since = 计时器起点(后置条件)
        base = ("project_id=?", (pid,)) if pid else ("1=1", ())
        sql = f"{base[0]}{' AND ' + extra if extra else ''}"
        params = (*base[1], *extra_params)
        if since:
            sql += " AND created_at >= ?"
            params = (*params, since)
        return sql, params

    with tx() as conn:
        def agg(where: str, *wparams) -> dict:
            c, p = conds(where, *wparams)
            rows = conn.execute(
                f"SELECT source, COALESCE(SUM(delta),0) AS d FROM word_count_log"
                f" WHERE {c} GROUP BY source", p).fetchall()
            return {r["source"]: r["d"] for r in rows}

        def ai_ms(where: str, *wparams) -> int:
            """AI 用时(二期②柱状图悬浮口径):该时间窗内 ai_usage_logs 时长和。"""
            c, p = conds(where, *wparams)
            row = conn.execute(
                f"SELECT COALESCE(SUM(duration_ms),0) AS d FROM ai_usage_logs WHERE {c}",
                p).fetchone()
            return int(row["d"] or 0)

        today = agg("created_at >= ?", day_start)
        hour = agg("created_at >= ?", hour_start)
        today_ai_ms = ai_ms("created_at >= ?", day_start)
        # 近 24 小时逐小时柱状(负增量计入净额)
        buckets = []
        for i in range(23, -1, -1):
            lo = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
            hi = lo + timedelta(hours=1)
            c, p = conds("created_at >= ? AND created_at < ?", lo.isoformat(), hi.isoformat())
            rows = conn.execute(
                "SELECT source, COALESCE(SUM(delta),0) AS d FROM word_count_log"
                f" WHERE {c} GROUP BY source", p).fetchall()
            d = {r["source"]: r["d"] for r in rows}
            buckets.append({"hour": lo.strftime("%H:00"), "human": d.get("human", 0),
                            "ai": d.get("ai", 0), "ai_ms": ai_ms(
                                "created_at >= ? AND created_at < ?", lo.isoformat(), hi.isoformat())})
        # 近 7 日(总览卡趋势)
        week = []
        for i in range(6, -1, -1):
            lo = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            hi = lo + timedelta(days=1)
            c, p = conds("created_at >= ? AND created_at < ?", lo.isoformat(), hi.isoformat())
            rows = conn.execute(
                "SELECT source, COALESCE(SUM(delta),0) AS d FROM word_count_log"
                f" WHERE {c} GROUP BY source", p).fetchall()
            d = {r["source"]: r["d"] for r in rows}
            week.append({"day": lo.strftime("%m-%d"), "human": d.get("human", 0),
                         "ai": d.get("ai", 0), "ai_ms": ai_ms(
                             "created_at >= ? AND created_at < ?", lo.isoformat(), hi.isoformat())})
        chapter = {"human": 0, "ai": 0}
        if node_id:
            rows = conn.execute(
                "SELECT source, COALESCE(SUM(delta),0) AS d FROM word_count_log"
                " WHERE project_id=? AND node_id=? GROUP BY source", (pid, node_id)).fetchall()
            chapter = {r["source"]: r["d"] for r in rows}
    return {
        "today": {"human": today.get("human", 0), "ai": today.get("ai", 0),
                  "ai_ms": today_ai_ms},
        "hour": {"human": hour.get("human", 0), "ai": hour.get("ai", 0)},
        "since": (agg("created_at >= ?", since) if since else {"human": 0, "ai": 0}),
        "chapter": chapter,
        "last24h": buckets,
        "week": week,
        # 全库累计(2026-09-10 用户要"总字数显示"):该范围(pid 空=全部书)的
        # word_count_log 净额(负增量已计入,与今日/近7日同口径)
        "total": agg(""),
        "now": now.isoformat(),
    }


# ── 剧情时间线(C:故事内容视角)──

class EventIn(BaseModel):
    time_label: str = ""
    title: str
    summary: str = ""
    line: str = "主线"
    status: str = "未定"


@router.get("/books/{pid}/timeline-events")
def list_events(pid: str) -> dict:
    with tx() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM timeline_events WHERE project_id=? ORDER BY sort_key, created_at",
            (pid,)).fetchall()]
        for r in rows:
            r["chapters"] = [dict(c) for c in conn.execute(
                "SELECT n.id, n.title, n.status FROM event_chapters ec"
                " JOIN outline_nodes n ON n.id = ec.node_id WHERE ec.event_id=?"
                " ORDER BY n.sort_order", (r["id"],)).fetchall()]
    return {"events": rows}


@router.get("/{pid}/screen-time")
def screen_time(pid: str) -> dict:
    """人物戏份曲线(候选清单落地批 A):同框边 at_chapter 聚合每角色出场章号集。

    数据=人物板 kind='同框' 边(style.at_chapter);边两端角色各记一次同章出场。
    纯统计零 LLM;返回按出场章数降序。
    """
    import json as _json
    with tx() as conn:
        rows = conn.execute(
            "SELECT nf.label AS lf, nt.label AS lt, e.style FROM graph_edges e"
            " JOIN graph_boards b ON b.id = e.board_id"
            " JOIN graph_nodes nf ON nf.id = e.from_node_id"
            " JOIN graph_nodes nt ON nt.id = e.to_node_id"
            " WHERE b.project_id=? AND b.kind='character' AND e.kind='同框'", (pid,)).fetchall()
    apps: dict[str, set[int]] = {}
    for r in rows:
        try:
            no = int(_json.loads(r["style"] or "{}").get("at_chapter"))
        except (TypeError, ValueError, _json.JSONDecodeError):
            continue
        if no <= 0:
            continue
        for name in (r["lf"], r["lt"]):
            apps.setdefault(name, set()).add(no)
    roles = [{"name": k, "chapter_nos": sorted(v), "count": len(v)}
             for k, v in apps.items()]
    roles.sort(key=lambda x: (-x["count"], x["name"]))
    return {"roles": roles}


@router.post("/books/{pid}/timeline-events", status_code=201)
def create_event(pid: str, body: EventIn) -> dict:
    if not body.title.strip():
        raise HTTPException(422, "事件标题不能为空")
    if body.line not in ("主线", "支线") or body.status not in ("已定", "未定"):
        raise HTTPException(422, "line 只能是 主线/支线;status 只能是 已定/未定")
    eid = f"evt_{uuid.uuid4().hex[:20]}"
    with tx() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(404, "书不存在")
        sort_key = conn.execute(
            "SELECT COALESCE(MAX(sort_key)+1, 1) FROM timeline_events WHERE project_id=?",
            (pid,)).fetchone()[0]
        now = _now()
        conn.execute(
            "INSERT INTO timeline_events(id, project_id, time_label, title, summary, line,"
            " status, sort_key, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (eid, pid, body.time_label.strip(), body.title.strip(), body.summary.strip(),
             body.line, body.status, sort_key, now, now))
        row = dict(conn.execute("SELECT * FROM timeline_events WHERE id=?", (eid,)).fetchone())
    row["chapters"] = []
    return {"event": row}


def _get_event(conn, eid: str) -> dict:
    row = conn.execute("SELECT * FROM timeline_events WHERE id=?", (eid,)).fetchone()
    if row is None:
        raise HTTPException(404, "事件不存在")
    return dict(row)


class EventPatch(BaseModel):
    time_label: str | None = None
    title: str | None = None
    summary: str | None = None
    line: str | None = None
    status: str | None = None
    sort_key: int | None = None


@router.put("/timeline/{eid}")
def update_event(eid: str, body: EventPatch) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "无字段可更新")
    if patch.get("line") not in (None, "主线", "支线"):
        raise HTTPException(422, "line 只能是 主线/支线")
    if patch.get("status") not in (None, "已定", "未定"):
        raise HTTPException(422, "status 只能是 已定/未定")
    if patch.get("title") is not None and not patch["title"].strip():
        raise HTTPException(422, "事件标题不能为空")
    with tx() as conn:
        _get_event(conn, eid)
        sets = ", ".join(f"{k}=?" for k in patch)
        conn.execute(f"UPDATE timeline_events SET {sets}, updated_at=? WHERE id=?",
                     (*patch.values(), _now(), eid))
    return {"ok": True}


@router.delete("/timeline/{eid}")
def delete_event(eid: str) -> dict:
    with tx() as conn:
        _get_event(conn, eid)
        conn.execute("DELETE FROM event_chapters WHERE event_id=?", (eid,))
        conn.execute("DELETE FROM timeline_events WHERE id=?", (eid,))
    return {"ok": True}


@router.get("/timeline/{eid}/detail")
def event_detail(eid: str) -> dict:
    with tx() as conn:
        evt = _get_event(conn, eid)
        evt["chapters"] = [dict(c) for c in conn.execute(
            "SELECT n.id, n.title, n.status FROM event_chapters ec"
            " JOIN outline_nodes n ON n.id = ec.node_id WHERE ec.event_id=?"
            " ORDER BY n.sort_order", (eid,)).fetchall()]
        for c in evt["chapters"]:
            c["status_label"] = STATUS_LABELS.get(c["status"], c["status"])
        # 可挂章全集(挂章选择器数据源)
        evt["all_chapters"] = [dict(c) for c in conn.execute(
            "SELECT id, title, status FROM outline_nodes WHERE project_id=? AND kind='chapter'"
            " ORDER BY sort_order", (evt["project_id"],)).fetchall()]
        hist = [dict(h) for h in conn.execute(
            "SELECT field, before, after, source, created_at FROM outline_field_history"
            " WHERE node_id=? AND node_type='event' ORDER BY created_at DESC LIMIT 20",
            (eid,)).fetchall()]
    evt["field_history"] = hist
    return {"event": evt}


class EventChapterIn(BaseModel):
    node_id: str


@router.post("/timeline/{eid}/chapters", status_code=201)
def link_chapter(eid: str, body: EventChapterIn) -> dict:
    with tx() as conn:
        _get_event(conn, eid)
        if conn.execute("SELECT 1 FROM outline_nodes WHERE id=?", (body.node_id,)).fetchone() is None:
            raise HTTPException(404, "章节点不存在")
        conn.execute(
            "INSERT OR IGNORE INTO event_chapters(event_id, node_id) VALUES(?,?)",
            (eid, body.node_id))
    return {"ok": True}


@router.delete("/timeline/{eid}/chapters/{node_id}")
def unlink_chapter(eid: str, node_id: str) -> dict:
    with tx() as conn:
        conn.execute("DELETE FROM event_chapters WHERE event_id=? AND node_id=?",
                     (eid, node_id))
    return {"ok": True}


# 角色关系旧表(character_relations,v10 语义冻结)的 API 读链已下线
# (2026-09-06 审计 S2:唯一 UI 调用方 RelationGraphPanel 已随 S10(a) 删除,
# 数据已一次性迁入统一图谱引擎,旧表仅留库作对照,不再有读端点)。
