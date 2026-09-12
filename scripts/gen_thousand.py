"""批次七①:千章测评 runner——逐章生产工作台管道(qwen 主/glm 兜底),断点续跑。

测评口径(用户拍板):连续性不作项;指标=完成率/耗时/成本(图谱渲染/大纲展示
由图谱优化件另行校准)。走生产管道:计划卡→草稿→规整→代码审计→自动豁免
失败项→合入 l4(+md 镜像);LLM 七维评审不跑(advisory 件,不在指标内)。
成本经 chat_completion 自动入台账(ai_usage_logs/agent_runs),与产品同账,
无需 runner 记第二本账。

用法(在 backend 目录,用 backend/.venv):
  .venv/Scripts/python.exe ../scripts/gen_thousand.py --limit 10    # 首 10 章实测(点火前预估)
  .venv/Scripts/python.exe ../scripts/gen_thousand.py --limit 1000  # 正式千章(⏸ 用户口令后)

断点续跑:进度落 data/eval_thousand/progress.json,重跑自动跳过已完成
(有 l4 正文或进度 status=ok 的章);中断后原命令再跑即续。
主模型 qwen3.8-flash(思考链经 llm.extra 透传关闭);失败章切 glm-4.7-flash
重试一次后切回。开跑即切换全局三件套为 qwen,结束(含异常)恢复原样。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.llm.atomic_io import write_json_atomic  # noqa: E402
from app.routers.changeset_ops import (  # noqa: E402
    _changeset_view, _code_audit, _open_changeset)
from app.routers.generation import _generate_draft_text  # noqa: E402
from app.routers.settings_api import SwitchIn, llm_switch  # noqa: E402
from app.routers.workbench import (  # noqa: E402
    _replace_changeset, apply_changeset_internal)
from app.db import tx  # noqa: E402
from app.common import _now  # noqa: E402
from app.settings_store import (  # noqa: E402
    get_api_key, get_settings, set_api_key, update_settings)

DEFAULT_PROJECT = "proj_ff3ee93689de4d90a9f3"   # 千章图谱实测书(2000 章,全部未写)
PROGRESS_PATH = Path(__file__).resolve().parents[1] / "data" / "eval_thousand" / "progress.json"
QWEN_MODEL = "qwen3.8-flash"
FALLBACK = {"provider": "glm", "model": "glm-4.7-flash"}
DISMISS_NOTE = "千章测评:批量跑自动豁免(指标不含审计质量判定)"
ABORT_AFTER_CONSECUTIVE_FAILS = 5

_progress_lock = threading.Lock()
_fallback_lock = threading.Lock()


def _load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"chapters": {}, "started_at": None}


def _save_progress(prog: dict) -> None:
    with _progress_lock:
        write_json_atomic(PROGRESS_PATH, prog)


def _ensure_qwen_pricing() -> None:
    """qwen3.8-flash 价格入册(缺才补,不覆盖手工改动);成本口径 0.8/2.7/缓存 0.1。"""
    models = get_settings()["pricing"].get("models", [])
    if any(m.get("model") == QWEN_MODEL for m in models):
        return
    models.append({"model": QWEN_MODEL, "input_per_m": 0.8, "output_per_m": 2.7,
                   "cache_input_per_m": 0.1})
    update_settings("pricing", {"models": models})


def _switch_qwen_off_thinking() -> None:
    llm_switch(SwitchIn(provider="qwen"))
    update_settings("llm", {"extra": {"enable_thinking": False}})


def _switch_fallback() -> None:
    """兜底切换(glm-4.7-flash):只在 fallback_lock 内调用,用后须 _switch_qwen_back。"""
    llm_switch(SwitchIn(provider=FALLBACK["provider"]))
    update_settings("llm", {"model": FALLBACK["model"]})


def _switch_qwen_back() -> None:
    _switch_qwen_off_thinking()


def _ordered_chapters(pid: str) -> list[dict]:
    """全章按(卷序, 卷内序)排——正式跑从第一卷顺写,大纲/图谱展示有连续故事感。"""
    with tx() as conn:
        rows = conn.execute(
            "SELECT n.id, n.title, n.status, n.sort_order,"
            " COALESCE(p.sort_order, 9999) AS vol_order"
            " FROM outline_nodes n LEFT JOIN outline_nodes p ON p.id = n.parent_id"
            " WHERE n.project_id=? AND n.kind='chapter'"
            " ORDER BY vol_order, n.sort_order, n.id", (pid,)).fetchall()
    return [dict(r) for r in rows]


def _has_l4(nid: str) -> bool:
    with tx() as conn:
        return conn.execute("SELECT 1 FROM l4_texts WHERE node_id=?", (nid,)).fetchone() is not None


def _dismiss_failed(nid: str) -> int:
    """豁免当前变更集全部未豁免失败项并落库,返回条数(审计质量指标原始数据)。"""
    cs = _open_changeset(nid)
    if cs is None:
        return 0
    view = _changeset_view(cs)
    failed = [v for v in view["validations"] if v.get("status") == "failed" and not v.get("dismissed")]
    if not failed:
        return 0
    for v in failed:
        v["dismissed"] = True
        v["dismiss_note"] = DISMISS_NOTE
    with tx() as conn:
        conn.execute("UPDATE changesets SET validations=?, updated_at=? WHERE id=?",
                     (json.dumps(view["validations"], ensure_ascii=False), _now(), cs["id"]))
    return len(failed)


def _gen_one(pid: str, ch: dict, stage_times: dict) -> tuple[str, dict, list]:
    """单章管道:计划卡→草稿→规整;返回 (草稿, 计划卡, 调用记录)。"""
    def progress(stage: str) -> None:
        stage_times[stage] = round(time.monotonic(), 3)

    node = {"id": ch["id"], "title": ch["title"], "status": ch["status"]}
    draft, plan, calls = _generate_draft_text(
        pid, node, force_new_plan=False, skill=None, progress=progress)
    return draft, plan, calls


def _run_chapter(pid: str, ch: dict) -> dict:
    """跑一章并落全部指标;异常向上抛由调用方记失败。"""
    t0 = time.monotonic()
    stage_times: dict = {}
    draft, plan, calls = _gen_one(pid, ch, stage_times)
    stage_elapsed = {}
    ordered = ["plan", "draft", "normalize"]
    marks = [s for s in ordered if s in stage_times]
    for i, s in enumerate(marks):
        end = stage_times[marks[i + 1]] if i + 1 < len(marks) else time.monotonic()
        stage_elapsed[s] = round(end - stage_times[s], 1)
    validations, _ = _code_audit(pid, {"id": ch["id"], "title": ch["title"]}, draft)
    cs = _open_changeset(ch["id"])
    _replace_changeset(pid, {"id": ch["id"], "title": ch["title"], "status": ch["status"]},
                       draft, plan, validations, None, cs)
    dismissed = _dismiss_failed(ch["id"])
    apply_changeset_internal(ch["id"], pid)
    cost = round(sum(c["usage"]["cost_total"] for c in calls), 6)
    return {
        "status": "ok", "seconds": round(time.monotonic() - t0, 1),
        "stages": stage_elapsed, "cost": cost,
        "chars": len(draft), "dismissed": dismissed,
        "calls": len(calls),
        "request_tokens": sum(int(c["usage"].get("request_tokens") or 0) for c in calls),
        "response_tokens": sum(int(c["usage"].get("response_tokens") or 0) for c in calls),
        "cached_tokens": sum(int(c["usage"].get("cached_tokens") or 0) for c in calls),
        "models": sorted({c["model"] for c in calls}),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="千章测评 runner(批次七①)")
    ap.add_argument("--project", default=DEFAULT_PROJECT, help="书 id(默认千章图谱实测书)")
    ap.add_argument("--limit", type=int, default=0, help="本次最多跑几章(0=全部剩余)")
    ap.add_argument("--until", type=int, default=0, help="写到第 N 章号停(含;0=不限,"
                    "章号取标题「第N章」;候选清单落地批 2026-09-10 防跨卷超写)")
    ap.add_argument("--workers", type=int, default=1, help="并发章数(默认 1 串行)")
    args = ap.parse_args()

    pid = args.project
    chapters = _ordered_chapters(pid)
    if not chapters:
        print(f"书 {pid} 无章节节点", flush=True)
        return 1
    prog = _load_progress()
    prog.setdefault("chapters", {})
    todo = [c for c in chapters
            if not _has_l4(c["id"]) and prog["chapters"].get(c["id"], {}).get("status") != "ok"]
    if args.limit:
        todo = todo[:args.limit]
    if args.until:
        def _no(c: dict):
            m = re.search(r"第(\d+)章", c.get("title", ""))
            return int(m.group(1)) if m else None
        before = len(todo)
        todo = [c for c in todo
                if (n := _no(c)) is not None and n <= args.until]
        print(f"--until {args.until}: 待跑 {before} → {len(todo)} 章", flush=True)
    if not todo:
        print("没有待跑章节(全部已有正文或进度标记完成)", flush=True)
        return 0

    print(f"== 千章测评 ==书 {pid} 全 {len(chapters)} 章,待跑 {len(todo)} 章"
          f"(workers={args.workers}),进度档 {PROGRESS_PATH}", flush=True)

    # 切 qwen(思考链关);快照现场,任何退出路径都恢复
    _ensure_qwen_pricing()
    snap_llm = dict(get_settings()["llm"])
    snap_key = get_api_key()
    _switch_qwen_off_thinking()
    print("已切换主模型:", get_settings()["llm"]["model"],
          "| extra:", get_settings()["llm"].get("extra"), flush=True)

    consecutive_fails = 0
    aborted = False

    def restore() -> None:
        update_settings("llm", snap_llm)
        set_api_key(snap_key)
        print("已恢复原三件套:", get_settings()["llm"].get("provider_name"),
              get_settings()["llm"].get("model"), flush=True)

    def work(i_ch: tuple[int, dict]) -> bool:
        nonlocal consecutive_fails, aborted
        i, ch = i_ch
        label = f"[{i + 1}/{len(todo)}] {ch['title']}({ch['id'][:14]}…)"
        try:
            m = _run_chapter(pid, ch)
            prog["chapters"][ch["id"]] = {**m, "title": ch["title"]}
            _save_progress(prog)
            print(f"{label} ok {m['seconds']}s ¥{m['cost']:.4f} {m['chars']}字"
                  f" 豁免{m['dismissed']} 阶段{m['stages']}", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001 单章失败不断线
            err = str(exc)[:300]
            prog["chapters"][ch["id"]] = {"status": "failed", "error": err,
                                          "title": ch["title"],
                                          "finished_at": datetime.now(timezone.utc).isoformat()}
            _save_progress(prog)
            print(f"{label} FAIL {err}", flush=True)
            # 兜底:疑似限流/服务端错→切 glm 重试本章一次,再回 qwen(串行锁防来回横跳)
            with _fallback_lock:
                try:
                    m = _run_chapter(pid, ch)
                    m["fallback"] = FALLBACK["model"]
                    prog["chapters"][ch["id"]] = {**m, "title": ch["title"]}
                    _save_progress(prog)
                    print(f"{label} ok(兜底 {FALLBACK['model']}){m['seconds']}s"
                          f" ¥{m['cost']:.4f} {m['chars']}字", flush=True)
                    return True
                except Exception as exc2:  # noqa: BLE001 兜底也失败=真失败
                    prog["chapters"][ch["id"]] = {
                        "status": "failed", "error": str(exc2)[:300], "title": ch["title"],
                        "finished_at": datetime.now(timezone.utc).isoformat()}
                    _save_progress(prog)
                    print(f"{label} FAIL(兜底后) {exc2}", flush=True)
                    return False

    try:
        prog["started_at"] = prog.get("started_at") or datetime.now(timezone.utc).isoformat()
        _save_progress(prog)
        if args.workers <= 1:
            for pair in enumerate(todo):
                if aborted:
                    break
                ok = work(pair)
                consecutive_fails = 0 if ok else consecutive_fails + 1
                if consecutive_fails >= ABORT_AFTER_CONSECUTIVE_FAILS:
                    print(f"连续 {consecutive_fails} 章失败,中止(进度已存,排查后原命令续跑)",
                          flush=True)
                    aborted = True
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for ok in pool.map(work, enumerate(todo)):
                    consecutive_fails = 0 if ok else consecutive_fails + 1
                    if consecutive_fails >= ABORT_AFTER_CONSECUTIVE_FAILS:
                        print(f"连续 {consecutive_fails} 章失败,中止", flush=True)
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
    finally:
        done = sum(1 for c in prog["chapters"].values() if c.get("status") == "ok")
        failed = sum(1 for c in prog["chapters"].values() if c.get("status") == "failed")
        cost = round(sum(c.get("cost", 0) for c in prog["chapters"].values()), 4)
        secs = [c["seconds"] for c in prog["chapters"].values() if c.get("seconds")]
        print(f"== 小结 ==完成 {done} 失败 {failed} 累计成本 ¥{cost}"
              f" 均耗 {round(sum(secs) / len(secs), 1) if secs else 0}s/章", flush=True)
        restore()
    return 0 if not aborted else 2


if __name__ == "__main__":
    sys.exit(main())
