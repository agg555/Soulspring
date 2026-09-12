"""每日自动备份(2026-09-10 拍板"小活高价值"):书稿数据无价,DB 单文件是
唯一真源,日常实跑期间的产出不能只靠手动 push 备份仓。

机制:lifespan 起守护线程——服务启动即快照一次,之后每 24h 一次;
sqlite3.Connection.backup 在线备份(WAL 安全,无需停服),落
data/backups/soulspring-YYYYMMDD-HHMMSS.db,保留最近 KEEP 份,超出删最旧。
零配置:备份失败只落日志,不干扰服务。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from .db import get_conn

BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
INTERVAL_SECONDS = 24 * 3600
KEEP = 14   # 保留份数(一天一份约两周回溯窗口)


def backup_now(target_dir: Path | None = None) -> Path:
    """在线快照一次,返回备份文件路径(sqlite backup API,页级复制,可带 WAL)。

    target_dir 默认参看 BACKUP_DIR(运行时取,留 None 便于测试替换目录)。
    """
    target_dir = target_dir or BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / f"soulspring-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = get_conn()
    with sqlite3.connect(dest) as out:
        src.backup(out)
    return dest


def prune_old(target_dir: Path | None = None, keep: int = KEEP) -> int:
    """按文件名时间戳排序删超出保留份数的旧快照,返回删除数。

    target_dir 运行时取(默认 BACKUP_DIR):不用默认参数绑定——定义期绑定会让
    测试 monkeypatch 模块属性失效,守护线程测试的清理会打到真备份目录。
    """
    target_dir = target_dir or BACKUP_DIR
    snaps = sorted(
        (p for p in target_dir.glob("soulspring-*.db") if p.is_file()),
        key=lambda p: p.name,
    )
    for p in snaps[: max(0, len(snaps) - keep)]:
        p.unlink()
    return max(0, len(snaps) - keep)


def _log(msg: str) -> None:
    from .stability import _log as stability_log
    stability_log("backup.log", msg)


def _loop() -> None:
    # 启动即备一次(服务活着=数据有守护;重启频率不影响,重名靠时间戳)
    while True:
        try:
            dest = backup_now()
            removed = prune_old()
            _log(f"快照完成 {dest.name}(清理旧快照 {removed} 份)")
        except Exception as exc:  # noqa: BLE001 备份失败绝不干扰服务
            _log(f"快照失败: {type(exc).__name__}: {exc}")
        time.sleep(INTERVAL_SECONDS)


def start_backup_daemon() -> threading.Thread:
    t = threading.Thread(target=_loop, name="daily-backup", daemon=True)
    t.start()
    return t
