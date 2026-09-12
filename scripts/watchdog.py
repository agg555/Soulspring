"""看门狗启动器(批次四①):调 backend/app/stability.py 的守护循环。

独立入口供 启动-看门狗.bat 使用;日志与退避逻辑单一正本在 stability.py。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.stability import run_watchdog  # noqa: E402

if __name__ == "__main__":
    run_watchdog(sys.argv[1] if len(sys.argv) > 1 else "8600")
