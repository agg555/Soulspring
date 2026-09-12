"""文本导入(批次三①)回归:切分器纯算法各形态 + 三去向闸门 + 批准/驳回流。"""
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.chaishu import (  # noqa: E402
    TextImportApproveIn,
    TextImportIn,
    _split_text,
    text_import,
    text_import_approve,
    text_import_reject,
    text_imports,
)


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    yield dbmod


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 切分器(纯算法,无库)─────────────────────────────────────────────

def test_split_by_chapter_marks():
    text = "第一章 复诊\n正文甲。\n正文乙。\n第二章 探视时间\n正文丙。"
    chapters, warnings = _split_text(text)
    assert [c["title"] for c in chapters] == ["第一章 复诊", "第二章 探视时间"]
    assert chapters[0]["content"] == "正文甲。\n正文乙。"
    assert chapters[1]["chars"] == 4
    assert warnings == []


def test_split_md_fallback_and_no_marks():
    md = "# 开端\n甲甲甲。\n# 转折\n乙乙乙。"
    chapters, warnings = _split_text(md)
    assert [c["title"] for c in chapters] == ["开端", "转折"]
    assert any("Markdown" in w for w in warnings)
    no_mark_chapters, no_mark_warnings = _split_text("就是一段没有标记的散文。")
    assert len(no_mark_chapters) == 1 and no_mark_chapters[0]["chars"] == len("就是一段没有标记的散文。")
    assert any("整篇作为单节" in w for w in no_mark_warnings)


def test_split_preface_and_oversize_warnings():
    preface = "楔子:这是标记前的一小段。\n"
    body = "第一章 甲\n" + "字" * 20001 + "\n第二章 乙\n短。"
    chapters, warnings = _split_text(preface + body)
    assert len(chapters) == 2
    assert any("标记前" in w for w in warnings)
    assert any("超 2 万字" in w for w in warnings)
    assert chapters[0]["chars"] == 20001


# ── 三去向闸门与批准流(带库)───────────────────────────────────────────

def _mk_project(dbmod) -> str:
    pid = f"proj_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at) VALUES(?,?,?,?)",
            (pid, "导入书", _now(), _now()))
    return pid


def _mk_volume(dbmod, pid: str, title: str = "第一卷") -> str:
    vid = f"on_{uuid.uuid4().hex[:12]}"
    with dbmod.tx() as conn:
        conn.execute(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
            " created_at, updated_at) VALUES(?,?,NULL,'volume',?,?,?)",
            (vid, pid, title, _now(), _now()))
    return vid


def test_l1_target_goes_to_proposal_area(tmp_db):
    pid = _mk_project(tmp_db)
    text = "第一章 设定甲\n内容甲。\n第二章 设定乙\n内容乙。"
    result = text_import(TextImportIn(
        project_id=pid, text=text, source_name="自设.md", target="l1"))
    assert result["count"] == 2 and "提案区" in result["message"]
    with tmp_db.tx() as conn:
        rows = conn.execute(
            "SELECT name, entry_status, source FROM l1_entries"
            " WHERE project_id=? ORDER BY name", (pid,)).fetchall()
    assert [r["name"] for r in rows] == ["第一章 设定甲", "第二章 设定乙"]
    assert all(r["entry_status"] == "proposal" and r["source"] == "import" for r in rows)


def test_outline_import_requires_volume(tmp_db):
    pid = _mk_project(tmp_db)
    with pytest.raises(HTTPException) as e:
        text_import(TextImportIn(project_id=pid, text="第一章 甲\n乙。",
                                 target="outline", volume_id=None))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        text_import(TextImportIn(project_id=pid, text="第一章 甲\n乙。",
                                 target="outline", volume_id="on_nosuch"))
    assert e.value.status_code == 422


def test_outline_approve_creates_chapters_once(tmp_db):
    pid = _mk_project(tmp_db)
    vid = _mk_volume(tmp_db, pid)
    result = text_import(TextImportIn(
        project_id=pid, text="第一章 甲\n乙。", target="outline", volume_id=vid))
    jid = result["job_id"]
    listing = text_imports(project_id=pid)["jobs"]
    assert listing[0]["status"] == "awaiting_approval" and listing[0]["count"] == 1
    approved = text_import_approve(jid, TextImportApproveIn())
    assert approved["created"] == 1
    with tmp_db.tx() as conn:
        row = conn.execute(
            "SELECT parent_id, kind, status FROM outline_nodes WHERE id=?",
            (approved["node_ids"][0],)).fetchone()
    assert row["parent_id"] == vid and row["kind"] == "chapter" and row["status"] == "unwritten"
    with pytest.raises(HTTPException) as e:  # 闸门:批准即终,二次处理拒绝
        text_import_approve(jid, TextImportApproveIn())
    assert e.value.status_code == 409


def test_manuscript_approve_lands_l4_and_reject(tmp_db):
    pid = _mk_project(tmp_db)
    vid = _mk_volume(tmp_db, pid)
    jid = text_import(TextImportIn(
        project_id=pid, text="第一章 甲\n这是正文。\n第二章 乙\n正文乙。",
        target="manuscript", volume_id=vid))["job_id"]
    approved = text_import_approve(jid, TextImportApproveIn())
    assert approved["created"] == 2
    with tmp_db.tx() as conn:
        l4 = conn.execute(
            "SELECT t.content, n.status FROM l4_texts t"
            " JOIN outline_nodes n ON n.id=t.node_id ORDER BY n.title").fetchall()
    assert [r["status"] for r in l4] == ["draft", "draft"]
    assert l4[0]["content"] == "这是正文。"
    # 驳回流:新提案驳回后不可再批准
    jid2 = text_import(TextImportIn(
        project_id=pid, text="第一章 丙\n丁。", target="manuscript",
        volume_id=vid))["job_id"]
    assert text_import_reject(jid2)["ok"] is True
    with pytest.raises(HTTPException) as e:
        text_import_approve(jid2, TextImportApproveIn())
    assert e.value.status_code == 409
