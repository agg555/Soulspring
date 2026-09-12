"""批次四③回归:全书镜像目录结构与库一致/无正文书空镜像/书不存在报错。"""
import sys
import tempfile
import uuid
from datetime import datetime, timezone
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


import app.mirror as mirror_mod  # noqa: E402
from app.mirror import build_mirror  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_book(dbmod, name: str) -> str:
    pid = f"proj_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                     (pid, name, _now(), _now()))
    return pid


def test_mirror_full_structure(tmp_db, monkeypatch):
    monkeypatch.setattr(mirror_mod, "_DATA_DIR", Path(tempfile.mkdtemp()) / "data")
    pid = _mk_book(tmp_db, "镜像书")
    with tmp_db.tx() as conn:
        conn.execute(
            "INSERT INTO outline_nodes(id,project_id,parent_id,kind,title,created_at,updated_at)"
            " VALUES('v1',?,NULL,'volume','第一卷',?,?)", (pid, _now(), _now()))
        conn.execute(
            "INSERT INTO outline_nodes(id,project_id,parent_id,kind,title,created_at,updated_at)"
            " VALUES('c1',?,'v1','chapter','第一章',?,?)", (pid, _now(), _now()))
        conn.execute(
            "INSERT INTO l4_texts(node_id,content,updated_at) VALUES('c1','这是正文。',?)",
            (_now(),))
        conn.execute(
            "INSERT INTO l1_entries(id,project_id,category,name,content,entry_status,"
            "created_at,updated_at) VALUES('e1',?,'character','林晚','主角。','confirmed',?,?)",
            (pid, _now(), _now()))
        conn.execute(
            "INSERT INTO timeline_events(id,project_id,time_label,title,line,status,"
            "created_at,updated_at) VALUES('t1',?,'第一天','开幕','主线','未定',?,?)",
            (pid, _now(), _now()))
    with tmp_db.tx() as conn:
        result = build_mirror(conn, pid)
    base = Path(result["dir"])
    assert (base / "正文" / "第一卷" / "第一章.md").read_text(encoding="utf-8").rstrip().endswith("这是正文。")
    assert "林晚" in (base / "设定" / "人物设定.md").read_text(encoding="utf-8")
    assert "第一卷" in (base / "大纲.md").read_text(encoding="utf-8")
    assert "开幕" in (base / "时间线.md").read_text(encoding="utf-8")
    assert result["files"] == 4


def test_mirror_empty_book(tmp_db, monkeypatch):
    monkeypatch.setattr(mirror_mod, "_DATA_DIR", Path(tempfile.mkdtemp()) / "data")
    pid = _mk_book(tmp_db, "空书")
    with tmp_db.tx() as conn:
        result = build_mirror(conn, pid)
    base = Path(result["dir"])
    assert (base / "大纲.md").exists() and "(空大纲)" in (base / "大纲.md").read_text(encoding="utf-8")
    assert result["files"] == 2   # 仅 大纲+时间线,无正文无设定
