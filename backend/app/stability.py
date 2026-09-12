"""批次四①:稳定性兜底——全局异常处理 + 看门狗自愈(执行书-批次四 §1①)。

设计约束(外脑建议+红队修正):
- 异常处理分级:原始栈+请求上下文写日志文件,给用户的只有统一中文壳——不掩盖真因也不漏栈;
- HTTPException 走 FastAPI 自带处理(detail 语义不变),本 handler 只兜"未捕获异常";
- 看门狗:守护拉起 uvicorn,退出即退避重启(5s/30s/300s,稳定运行 60s 重置计数),
  看护日志独立落盘——进程"无故消失"在用户视角变为"闪一下自动回来"。
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # backend/(看门狗 cwd 用)
DATA_DIR = Path(__file__).resolve().parents[2] / "data"   # 项目根 data(与 db.py 同口径)
LOG_DIR = DATA_DIR / "logs"
BACKOFFS = (5, 30, 300)
STABLE_SECONDS = 60


def _log(name: str, msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / name, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def log_error(msg: str) -> Path:
    """全局异常处理器落盘用:写 error-日期.log,返回日志路径(供响应引用)。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"error-{datetime.now():%Y%m%d}.log"
    with open(path, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")
    return path


def run_watchdog(port: str = "8600") -> None:
    """守护循环:拉起 uvicorn,退出即退避重启;稳定运行超阈值则重置退避。"""
    fails = 0
    _log("watchdog.log", f"看门狗启动(端口 {port})")
    while True:
        started = time.monotonic()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", port],
            cwd=str(ROOT))  # ROOT=backend(本文件位于 backend/app);勿再拼 backend
        code = proc.wait()
        ran = time.monotonic() - started
        if ran > STABLE_SECONDS:
            fails = 0
        backoff = BACKOFFS[min(fails, len(BACKOFFS) - 1)]
        fails += 1
        _log("watchdog.log",
             f"服务退出 code={code} 本次运行 {ran:.0f}s;{backoff}s 后第 {fails} 次重启")
        time.sleep(backoff)


if __name__ == "__main__":
    run_watchdog(sys.argv[1] if len(sys.argv) > 1 else "8600")
