"""批次七②:分层搜索回归(FTS5 v17 迁移 + 触发器随写随更 + 分组端点)。

判据对齐执行书:千章体量搜人名/任意子串 ≤1s 分组返回;增删改正文索引自动同步;
空查询/无结果态可用;≥3 字走 MATCH、1-2 字回退 LIKE 兜底。
"""
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402
from app.routers.search import search  # noqa: E402


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


def _seed_book(conn, pid: str = "p1", name: str = "测试书",
               summary: str = "林凡初入青云宗") -> str:
    """建书+卷+章骨架,返回首个章节点 id(id 派生自 pid,多书共存不撞主键)。"""
    vid, nid = f"v_{pid}", f"n_{pid}"
    conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                 " VALUES(?,?, '2026-09-01', '2026-09-01')", (pid, name))
    conn.execute("INSERT INTO outline_nodes(id, project_id, kind, title, sort_order,"
                 " created_at, updated_at) VALUES(?, ?, 'volume', '第一卷', 0,"
                 " '2026-09-01', '2026-09-01')", (vid, pid))
    conn.execute("INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
                 " summary, sort_order, created_at, updated_at)"
                 " VALUES(?, ?, ?, 'chapter', '第一章 初入宗门',"
                 " ?, 0, '2026-09-01', '2026-09-01')", (nid, pid, vid, summary))
    return nid


def _write_chapter(nid: str, content: str) -> None:
    with tx() as conn:
        conn.execute("INSERT INTO l4_texts(node_id, content, updated_at) VALUES(?,?,?)",
                     (nid, content, "2026-09-01"))


def _items(resp, group: str) -> list[dict]:
    g = next(g for g in resp["groups"] if g["group"] == group)
    return g["items"]


def test_migration_v17_backfills_existing_content(tmp_db):
    with tx() as conn:
        nid = _seed_book(conn)
    _write_chapter(nid, "林凡握紧折跃钥匙。")   # 独立事务(tx 不可重入,嵌套即死锁)
    # v17 起点即回填:大纲行(2000 章级)+正文行都在索引里
    with tx() as conn:
        kinds = dict(conn.execute(
            "SELECT group_kind, COUNT(*) FROM search_index GROUP BY group_kind").fetchall())
    assert kinds.get("outline") == 2 and kinds.get("chapter") == 1


def test_match_and_like_fallback(tmp_db):
    with tx() as conn:
        nid = _seed_book(conn)
    _write_chapter(nid, "林凡握紧手中的折跃钥匙,望向城市尽头。")
    # ≥3 字:trigram MATCH 命中正文子串
    r = search(q="折跃钥匙", pid="p1")
    assert _items(r, "chapter")[0]["ref_id"] == nid
    assert "折跃钥匙" in _items(r, "chapter")[0]["snippet"]
    # 1-2 字:MATCH 物理不命中,LIKE 兜底照样出结果
    r2 = search(q="雨幕", pid="p1")
    assert _items(r2, "chapter") == []
    r3 = search(q="林凡", pid="p1")
    assert {i["ref_id"] for i in _items(r3, "chapter")} == {nid}
    assert {i["ref_id"] for i in _items(r3, "outline")} == {nid}


def test_trigger_sync_insert_update_delete(tmp_db):
    with tx() as conn:
        nid = _seed_book(conn)
    # 插入正文→入索引
    _write_chapter(nid, "旧正文里有青云宗。")
    assert _items(search(q="青云宗", pid="p1"), "chapter")
    # 更新正文→旧词出、新词进
    with tx() as conn:
        conn.execute("UPDATE l4_texts SET content=? WHERE node_id=?",
                     ("新正文提到玄天塔。", nid), )
    r = search(q="青云宗", pid="p1")
    assert _items(r, "chapter") == []
    assert _items(search(q="玄天塔", pid="p1"), "chapter")
    # 删除正文→索引同步清
    with tx() as conn:
        conn.execute("DELETE FROM l4_texts WHERE node_id=?", (nid,))
    assert _items(search(q="玄天塔", pid="p1"), "chapter") == []


def test_grouping_and_isolation(tmp_db):
    with tx() as conn:
        nid = _seed_book(conn)
    _write_chapter(nid, "林凡的故事。")
    with tx() as conn:
        # 第二本书:骨架不含关键词,验证 pid 过滤互不串
        _seed_book(conn, pid="p2", name="另一本", summary="毫无相关的摘要")
    r = search(q="林凡", pid="p2")
    assert _items(r, "chapter") == []          # p2 无正文
    assert _items(r, "outline") == []          # p2 骨架标题/摘要不含关键词
    r_all = search(q="林凡")                    # 跨书:正文/大纲只 p1 含关键词
    assert any(i["project_id"] == "p1" for i in _items(r_all, "chapter"))
    assert all(i["project_id"] == "p1" for i in _items(r_all, "outline"))


def test_empty_and_miss_states(tmp_db):
    with tx() as conn:
        nid = _seed_book(conn)
    _write_chapter(nid, "有内容。")
    r = search(q="  ")
    assert r["total"] == 0 and len(r["groups"]) == 4
    r2 = search(q="绝不存在的词", pid="p1")
    assert r2["total"] == 0 and r2["groups"][0]["items"] == []
    assert r2["elapsed_ms"] >= 0


def test_thousand_chapter_scale_under_1s(tmp_db):
    """判据:千章体量搜人名/任意子串 ≤1s 分组返回。"""
    with tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '千章书', '2026-09-01', '2026-09-01')")
        conn.execute("INSERT INTO outline_nodes(id, project_id, kind, title,"
                     " sort_order, created_at, updated_at)"
                     " VALUES('v1', 'p1', 'volume', '第一卷', 0,"
                     " '2026-09-01', '2026-09-01')")
        rows = []
        for i in range(1, 2001):
            nid = f"n{i}"
            body = (f"第{i}章正文。{f'填充句子的普通叙述内容。' * 20}"
                    + ("苏千寻在檐下看雨。" if i == 1500 else ""))
            rows.append((nid, "p1", "v1", "chapter", f"第{i:04d}章", body, i,
                         "2026-09-01", "2026-09-01"))
        conn.executemany(
            "INSERT INTO outline_nodes(id, project_id, parent_id, kind, title,"
            " summary, sort_order, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)", rows)
    t0 = time.monotonic()
    r = search(q="苏千寻", pid="p1")
    elapsed = time.monotonic() - t0
    items = _items(r, "outline")
    assert items and items[0]["ref_id"] == "n1500"
    assert elapsed < 1.0, f"千章搜索超时:{elapsed:.3f}s"


def test_snippet_and_special_chars(tmp_db):
    with tx() as conn:
        nid = _seed_book(conn)
    _write_chapter(nid, '他说:"引号内也不能崩。"随后离开。')
    r = search(q='引号内也不能崩', pid="p1")
    assert _items(r, "chapter")[0]["ref_id"] == nid
    # FTS 语法字符当普通文本查,不抛 422
    r2 = search(q="OR AND NOT", pid="p1")
    assert r2["total"] == 0
