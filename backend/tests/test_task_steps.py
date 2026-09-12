"""批次七③:工具调用过程实时显示回归(gen_task_steps + StepRecorder + 视图加厚)。

判据对齐任务词:每环节一行(工具/环节名/参数摘要/状态/起止/产物摘要);
轮询返回体(task_view)附带 steps;heal_stale 不留挂死的 running 步骤。
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402
from app.routers.task_runner import (  # noqa: E402
    StepRecorder, create_task, finish_task, heal_stale, start_step, steps_for,
    task_view,
)


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    yield dbmod
    dbmod._conn = None


def _seed_task() -> tuple[str, str]:
    """建书+章+任务行,返回 (tid, nid)。"""
    with tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO outline_nodes(id, project_id, kind, title,"
                     " created_at, updated_at)"
                     " VALUES('n1', 'p1', 'chapter', '第一章', '2026-09-01', '2026-09-01')")
    row = create_task("p1", {"id": "n1"}, "draft", None)
    return row["id"], "n1"


def test_step_lifecycle_seq_and_artifacts(tmp_db):
    tid, _ = _seed_task()
    rec = StepRecorder(tid)
    rec.begin("plan", tool="chat_completion@m1", params="计划卡 8000 上限")
    rec.begin("draft")                                  # begin 自动关上一步
    rec.annotate("plan", artifact="计划卡 5 键")          # 事后补记产物
    rec.finish_current(artifact="草稿 2451 字", tool="chat_completion@m1")
    rec.begin("audit")
    rec.finish_current(artifact="审计 3 项:CODE_X,CODE_Y", tool="code_audit")
    rec.close()

    steps = steps_for(tid)
    assert [s["name"] for s in steps] == ["plan", "draft", "audit"]
    assert all(s["status"] == "done" for s in steps)
    assert steps[0]["tool"] == "chat_completion@m1"
    assert steps[0]["artifact"] == "计划卡 5 键"
    assert steps[1]["artifact"] == "草稿 2451 字"
    assert "审计 3 项" in steps[2]["artifact"]
    assert [s["seq"] for s in steps] == [1, 2, 3]
    assert all(s["finished_at"] and s["duration_ms"] is not None for s in steps)


def test_task_view_carries_steps(tmp_db):
    tid, _ = _seed_task()
    rec = StepRecorder(tid)
    rec.begin("plan")
    rec.close()   # 中途查看:当前步已收,无挂死
    with tx() as conn:
        row = dict(conn.execute("SELECT * FROM gen_tasks WHERE id=?", (tid,)).fetchone())
    view = task_view(heal_stale(row))
    assert [s["name"] for s in view["steps"]] == ["plan"]


def test_heal_stale_marks_running_steps_error(tmp_db):
    tid, _ = _seed_task()
    start_step(tid, "draft")   # 模拟服务重启时挂着的 running 步骤
    from app.routers.task_runner import ACTIVE_NODES
    ACTIVE_NODES.clear()       # 注册表仅进程内存活;清空=模拟服务重启
    with tx() as conn:
        row = dict(conn.execute("SELECT * FROM gen_tasks WHERE id=?", (tid,)).fetchone())
    healed = heal_stale(row)   # ACTIVE_NODES 无注册 → 判定残留
    assert healed["status"] == "error"
    steps = steps_for(tid)
    assert steps[0]["status"] == "error"
    assert "中断" in steps[0]["artifact"]


def test_error_task_closes_step_as_error(tmp_db):
    tid, _ = _seed_task()
    rec = StepRecorder(tid)
    rec.begin("draft")
    try:
        raise RuntimeError("模型 500")
    except RuntimeError as exc:
        rec.close(status="error", artifact=str(exc)[:120])
        finish_task(tid, "n1", error=str(exc))
    steps = steps_for(tid)
    assert steps[0]["status"] == "error" and "模型 500" in steps[0]["artifact"]
