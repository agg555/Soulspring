"""原子写工具。

移植自 inkflow(inkflow/utils/atomic_io.py,MIT License,
Copyright (c) 2026 ElysiaQWQ;详见 THIRD-PARTY-NOTICES.md)。
同目录临时文件 + os.replace(),避免半写文件;自动建父目录。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "write_text_atomic",
    "write_bytes_atomic",
    "write_json_atomic",
]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件放同目录,保证 os.replace 原子性
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # 部分文件系统不支持 fsync,忽略
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_text_atomic(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    p = Path(path)
    _atomic_write(p, content.encode(encoding))


def write_bytes_atomic(path: str | Path, data: bytes) -> None:
    p = Path(path)
    _atomic_write(p, data)


def write_json_atomic(
    path: str | Path,
    obj: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
) -> None:
    text = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    write_text_atomic(path, text)
