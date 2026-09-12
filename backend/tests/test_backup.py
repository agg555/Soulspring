"""每日自动备份回归(2026-09-10):在线快照/保留份数清理/守护线程。"""
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
    yield dbmod
    dbmod._conn = None


def test_backup_now_creates_valid_db(tmp_db):
    """快照=合法 SQLite 且数据随行(建表后备份,新连接可读 user_version)。"""
    from app.backup import backup_now
    from app.db import tx
    with tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '备份验证', '2026-09-10', '2026-09-10')")
    dest = backup_now(Path(tempfile.mkdtemp()))
    assert dest.exists() and dest.stat().st_size > 0
    import sqlite3
    check = sqlite3.connect(dest)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] >= 22
        assert check.execute(
            "SELECT name FROM projects WHERE id='p1'").fetchone()[0] == "备份验证"
    finally:
        check.close()


def test_prune_keeps_latest(tmp_db):
    """保留份数:超出 KEEP 的最旧快照被删,最新保留。"""
    from app.backup import prune_old
    d = Path(tempfile.mkdtemp())
    names = [f"soulspring-2026090{i}-000000.db" for i in range(1, 6)]   # 5 份
    for n in names:
        (d / n).write_bytes(b"x")
    removed = prune_old(d, keep=3)
    assert removed == 2
    left = sorted(p.name for p in d.glob("soulspring-*.db"))
    assert left == names[2:]   # 最旧两份被删


def test_backup_daemon_thread_starts(tmp_db, monkeypatch):
    """守护线程可启动且为 daemon(不阻塞服务退出)。

    backup_now 必须打成假件:线程启动即真备份一轮,源=get_conn()(与后续测试
    的 tmp 库初始化存在线程竞态)、目标=BACKUP_DIR——两头都不许碰真库/真备份
    目录(2026-09-12 深查:本测试曾是间歇 UNIQUE 失败与真备份被清理的根源)。
    """
    from app import backup
    monkeypatch.setattr(backup, "BACKUP_DIR", Path(tempfile.mkdtemp()))
    monkeypatch.setattr(backup, "backup_now", lambda: Path("."))
    t = backup.start_backup_daemon()
    assert t.daemon is True
    assert t.is_alive()
