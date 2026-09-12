"""批次四①④回归:异常日志落盘/Origin 白名单纯函数/看门狗退避序列。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.stability import BACKOFFS, log_error  # noqa: E402


def test_log_error_writes_dated_file(tmp_path, monkeypatch):
    import app.stability as st
    monkeypatch.setattr(st, "LOG_DIR", tmp_path / "logs")
    path = log_error("[POST /x] 未捕获异常: ValueError: bad\nstack...")
    assert path.exists() and path.name.startswith("error-")
    text = path.read_text(encoding="utf-8")
    assert "ValueError: bad" in text and "stack..." in text
    path2 = log_error("second line")
    assert "second line" in path2.read_text(encoding="utf-8")  # 追加不覆盖


def test_origin_allowed_whitelist():
    """终审修复后按 netloc 判定:Origin 与带路径 Referer 都能正确放行/拒绝。"""
    from app.main import origin_allowed
    assert origin_allowed("http://127.0.0.1:8600")
    assert origin_allowed("http://localhost:8600/")
    assert origin_allowed("http://localhost:5173")          # dev server
    # 终审修复用例:Referer 带路径(旧实现 rstrip 后整串比对会误杀)
    assert origin_allowed("http://127.0.0.1:8600/books/x")
    assert origin_allowed("http://localhost:5173/some/deep/path")
    assert not origin_allowed("http://evil.example.com")
    assert not origin_allowed("https://127.0.0.1:8600")     # 协议不符
    assert not origin_allowed("http://127.0.0.1:9999")      # 端口不符
    assert not origin_allowed("http://127.0.0.1:8600.evil.com/path")  # 前缀伪装
    assert not origin_allowed("not a url")


def test_watchdog_backoff_sequence():
    assert BACKOFFS == (5, 30, 300) and len(BACKOFFS) >= 2
