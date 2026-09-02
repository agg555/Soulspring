"""拆书回归(S11,审计 2026-09-01):book_title 直接拼 output_dir,路径注入前置拒绝。"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

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


def test_book_title_rejects_path_tricks(tmp_db):
    """书名含路径分隔符/相对目录引用/空白名一律 422,不得落 output_dir。"""
    from app.routers.chaishu import JobIn, create_job
    for bad in ("../逃逸", "..\\逃逸", "a/b", "a\\b", ".", "..", "  ", ""):
        with pytest.raises(HTTPException) as ei:
            create_job(JobIn(project_id="p1", book_title=bad, source_path="x.txt"))
        assert ei.value.status_code == 422
