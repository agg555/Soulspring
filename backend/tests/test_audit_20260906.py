"""审计 2026-09-06 修复回归(报告 docs/审计-代码审查-2026-09-06.md §7)。

覆盖:H1 price_for 折扣过期只作用于未登记模型 / E区① v14 created_at 收紧重建迁移 /
S6 HTTP 层 ASGI 直连冒烟(免 TestClient 依赖,兜住路由挂载与请求解析)。
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture()
def tmp_db(monkeypatch):
    """独立临时库:重置全局连接后跑迁移,测试互不串库(同 test_batch1 夹具)。"""
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    yield dbmod
    dbmod._conn = None


# ── H1:折扣过期只作用于未登记模型 ──

def test_price_for_expiry_only_affects_unregistered_models(tmp_db):
    from app.settings_store import update_settings
    from app.ledger.usage import price_for

    update_settings("pricing", {
        "default": {"input_per_m": 0.4, "output_per_m": 1.4},
        "standard": {"input_per_m": 0.8, "output_per_m": 2.8},
        "discount_until": "2026-01-01",   # 已过期(固定日期,测试不含真实时钟依赖)
        "models": [{"model": "deepseek-v4-flash", "input_per_m": 1.5,
                    "output_per_m": 4.5, "cache_input_per_m": 0.05}],
    })
    # 在册模型:过期后仍按自身条目价(H1 修正点;原实现错记成 0.8/2.8)
    assert price_for("deepseek-v4-flash") == (1.5, 4.5, 0.05)
    # 未登记模型:过期后用 standard 正价(GLM 折扣到期的本意)
    assert price_for("glm-5.3-flash") == (0.8, 2.8, 0.8)
    assert price_for("whatever-else") == (0.8, 2.8, 0.8)
    # 未过期:未登记模型回落 default 折扣价,在册模型不变
    update_settings("pricing", {"discount_until": "2099-12-31"})
    assert price_for("glm-5.3-flash") == (0.4, 1.4, 0.4)
    assert price_for("deepseek-v4-flash") == (1.5, 4.5, 0.05)


def test_in_peak_window_deterministic():
    from datetime import datetime
    from app.ledger.usage import _in_peak_window
    # 2026-09-04 是周五;北京时间 10:30 = 高峰窗内,20:00 = 窗外;周六全天非高峰
    fri = datetime(2026, 9, 4, 10, 30)
    assert _in_peak_window("mon-fri 09-12,14-18", now=fri) is True
    assert _in_peak_window("mon-fri 09-12,14-18",
                           now=datetime(2026, 9, 4, 20, 0)) is False
    assert _in_peak_window("mon-fri 09-12,14-18",
                           now=datetime(2026, 9, 5, 10, 30)) is False  # 周六
    # 非法 schedule 宁便宜不错贵
    assert _in_peak_window("garbage", now=fri) is False


# ── E区①:v14 changeset_patches.created_at 收紧(重建式迁移)──

_LEGACY_DDL = """CREATE TABLE changeset_patches (
  id                TEXT PRIMARY KEY,
  changeset_id      TEXT NOT NULL REFERENCES changesets(id),
  target_type       TEXT NOT NULL DEFAULT 'chapter',
  target_id         TEXT NOT NULL,
  field             TEXT NOT NULL DEFAULT 'content',
  before_hash       TEXT NOT NULL DEFAULT '',
  expected_revision INTEGER,
  anchor            TEXT,
  before            TEXT,
  after             TEXT,
  reason            TEXT NOT NULL DEFAULT '',
  selected          INTEGER NOT NULL DEFAULT 1,
  applied_revision  INTEGER,
  version           INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT
)"""


def test_v14_rebuild_backfills_null_created_at(tmp_db):
    import app.db as dbmod
    with dbmod.tx() as conn:
        # 复刻 v3+v8 形状(created_at 可空),造一 NULL 一正常两行
        conn.execute("DROP TABLE changeset_patches")
        conn.execute(_LEGACY_DDL)
        conn.execute(
            "INSERT INTO projects(id, name, created_at, updated_at)"
            " VALUES('p1','测试书','2026-09-01','2026-09-01')")
        conn.execute(
            "INSERT INTO changesets(id, project_id, kind, status, payload, created_at)"
            " VALUES('cs_x','p1','draft','draft','{}','2026-09-01')")
        conn.execute(
            "INSERT INTO changeset_patches(id, changeset_id, target_id, version)"
            " VALUES('p_legacy','cs_x','n1',3)")   # created_at NULL(v3→v8 间存量形态)
        conn.execute(
            "INSERT INTO changeset_patches(id, changeset_id, target_id, version, created_at)"
            " VALUES('p_ok','cs_x','n1',4,'2026-09-01T00:00:00')")
    with dbmod.tx() as conn:
        dbmod._tighten_changeset_patches(conn)
        dbmod._tighten_changeset_patches(conn)   # 幂等:重跑不炸不重复
        rows = {r["id"]: r["created_at"]
                for r in conn.execute("SELECT id, created_at FROM changeset_patches")}
        notnull = [r["notnull"] for r in conn.execute("PRAGMA table_info(changeset_patches)")
                   if r["name"] == "created_at"]
        leftover = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='changeset_patches_tighten'").fetchone()
    assert rows == {"p_legacy": "", "p_ok": "2026-09-01T00:00:00"}
    assert notnull == [1]          # 已收紧 NOT NULL
    assert leftover is None        # 临时表已换名清场


def test_migrate_reaches_latest(tmp_db):
    assert tmp_db.get_conn().execute("PRAGMA user_version").fetchone()[0] == 22


# ── S6:HTTP 层冒烟(裸 ASGI 直连,不依赖 httpx/TestClient)──

def _asgi(path: str, method: str = "GET", body: dict | None = None):
    from app.main import app

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 80),
        "headers": [(b"host", b"127.0.0.1"), (b"content-type", b"application/json")],
    }
    raw = json.dumps(body).encode() if body is not None else b""
    state = {"status": 0, "body": b""}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            state["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            state["body"] += msg.get("body", b"")

    asyncio.run(app(scope, receive, send))
    try:
        return state["status"], json.loads(state["body"])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return state["status"], None


def test_smoke_http_endpoints(tmp_db):
    st, data = _asgi("/api/overview")
    assert st == 200 and isinstance(data, dict)
    # 建线(201)→ 消息列表(200)→ 未知会话(404 detail)→ 非法 owner_type(422)→ 删线(200)
    st, data = _asgi("/api/conversations", "POST",
                     {"owner_type": "chat_test", "name": "冒烟线"})
    assert st == 201 and data["session"]["id"]
    sid = data["session"]["id"]
    st, data = _asgi(f"/api/conversations/{sid}/messages")
    assert st == 200 and data["messages"] == []
    st, data = _asgi("/api/conversations/nope/messages")
    assert st == 404 and "会话不存在" in data["detail"]
    st, data = _asgi("/api/conversations", "POST", {"owner_type": "bogus", "name": "x"})
    assert st == 422 and "未知会话归属类型" in data["detail"]
    st, data = _asgi(f"/api/conversations/{sid}", "DELETE")
    assert st == 200 and data["ok"] is True
    # 设置写入路由(PUT + JSON body 解析)
    st, data = _asgi("/api/settings/budget", "PUT", {"per_chapter_alert": 0.3})
    assert st == 200 and data["ok"] is True
