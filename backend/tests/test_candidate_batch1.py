"""候选清单落地批 1 后端回归(2026-09-10):一键备份/推送回显/md 导出章节卡四行。"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    with __import__("app.db", fromlist=["tx"]).tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '导出书', '2026-09-10', '2026-09-10')")
    yield dbmod
    dbmod._conn = None


def test_backup_now_endpoint(tmp_db, monkeypatch):
    """立即快照端点:文件落盘且返回文件名。"""
    from pathlib import Path as P
    import app.backup as bk
    d = P(tempfile.mkdtemp())
    monkeypatch.setattr(bk, "BACKUP_DIR", d)
    from app.routers.settings_api import backup_now_endpoint
    r = backup_now_endpoint()
    assert r["ok"] is True and (d / r["file"]).exists()


def test_push_backup_reports_failure_gracefully(tmp_db, monkeypatch):
    """推送端点:git 失败不抛异常,返回码与输出尾回显(空仓库/无网络场景)。"""
    from app.routers.settings_api import push_backup
    r = push_backup()
    assert set(r) >= {"ok", "code", "output"}
    assert isinstance(r["output"], str)


def test_export_md_carries_chapter_card(tmp_db):
    """md 导出随章节卡四行;txt 维持纯正文(不带引用行)。"""
    from app.db import tx
    from app.routers.books import export_book
    with tx() as conn:
        conn.execute("INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
                     " summary, note, sort_order, status, created_at, updated_at)"
                     " VALUES('n1', 'p1', NULL, 'category', '总纲', '', '', 0,"
                     " 'unwritten', '2026-09-10', '2026-09-10')")
        conn.execute("INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
                     " summary, note, sort_order, status, created_at, updated_at)"
                     " VALUES('n2', 'p1', 'n1', 'volume', '第一卷', '', '', 0,"
                     " 'unwritten', '2026-09-10', '2026-09-10')")
        conn.execute("INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
                     " summary, note, sort_order, status, created_at, updated_at)"
                     " VALUES('ch1', 'p1', 'n2', 'chapter', '第1章 测试', '本章摘要',"
                     " '本章备注', 0, 'unwritten', '2026-09-10', '2026-09-10')")
        conn.execute("INSERT INTO l4_texts(node_id, content, updated_at)"
                     " VALUES('ch1', '正文内容。', '2026-09-10')")
        conn.execute("INSERT INTO timeline_events(id, project_id, title, created_at,"
                     " updated_at) VALUES('e1', 'p1', '测试事件', '2026-09-10', '2026-09-10')")
        conn.execute("INSERT INTO event_chapters(event_id, node_id) VALUES('e1', 'ch1')")
    md = export_book("p1", "md").body.decode("utf-8")
    assert "# 第1章 测试" in md and "正文内容。" in md
    assert "> 摘要:本章摘要" in md and "> 备注:本章备注" in md
    assert "> 关联事件:测试事件" in md
    txt = export_book("p1", "txt").body.decode("utf-8")
    assert "第1章 测试" in txt and "摘要:" not in txt
