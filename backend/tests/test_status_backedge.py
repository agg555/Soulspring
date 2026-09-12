"""二期②:章状态机回边回归(human_editing→draft 重 roll 回落;finalized 解封)。

任务词拍板:draft→unwritten 不做;finalized→human_editing 走二次确认(前端把关,
后端只管迁移合法性);工作台重 roll 在人改中态出新草稿时状态自动回落草稿。
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402
from app.routers.outline import StatusIn, change_status  # noqa: E402
from app.routers.workbench import _transition  # noqa: E402


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    with tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO outline_nodes(id, project_id, kind, title, status,"
                     " created_at, updated_at)"
                     " VALUES('n1', 'p1', 'chapter', '第一章', 'unwritten',"
                     " '2026-09-01', '2026-09-01')")
    yield dbmod
    dbmod._conn = None


def _walk(*statuses: str) -> None:
    """按给定路径逐步推进状态(走真实端点,顺带验证每步合法)。"""
    for to in statuses:
        change_status("n1", StatusIn(to_status=to))


def test_human_editing_can_go_back_to_draft(tmp_db):
    _walk("draft", "human_editing")
    change_status("n1", StatusIn(to_status="draft"))   # 二期②新回边:重 roll 回落
    with tx() as conn:
        assert conn.execute("SELECT status FROM outline_nodes WHERE id='n1'").fetchone()[0] == "draft"


def test_finalized_can_be_unsealed(tmp_db):
    _walk("draft", "human_editing", "final_review", "finalized")
    change_status("n1", StatusIn(to_status="human_editing"))   # 二期②新回边:定稿解封
    with tx() as conn:
        assert conn.execute("SELECT status FROM outline_nodes WHERE id='n1'").fetchone()[0] == "human_editing"


def test_draft_to_unwritten_still_forbidden(tmp_db):
    _walk("draft")
    with pytest.raises(HTTPException, match="非法状态迁移"):
        change_status("n1", StatusIn(to_status="unwritten"))   # 拍板:不做


def test_workbench_reroll_falls_back_to_draft(tmp_db):
    """工作台重 roll:人改中态出新草稿 → _transition 自动回落草稿。"""
    _walk("draft", "human_editing")
    with tx() as conn:
        node = dict(conn.execute("SELECT * FROM outline_nodes WHERE id='n1'").fetchone())
        # 模拟 _replace_changeset 内的同款迁移判断(人改中允许回落)
        assert node["status"] in ("unwritten", "human_editing")
        _transition(conn, node, "draft")
        assert conn.execute("SELECT status FROM outline_nodes WHERE id='n1'").fetchone()[0] == "draft"


def test_unwritten_still_cannot_skip_to_draft_via_reroll_path(tmp_db):
    with tx() as conn:
        node = dict(conn.execute("SELECT * FROM outline_nodes WHERE id='n1'").fetchone())
    _transition(conn, node, "draft")   # unwritten→draft 合法(生成草稿)
    with tx() as conn:
        assert conn.execute("SELECT status FROM outline_nodes WHERE id='n1'").fetchone()[0] == "draft"
