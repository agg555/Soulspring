"""批次甲:L1 档案库树形化回归(同类别自由嵌套/换父防环/级联删/零消费语义变更)。

用户形态对齐(神陨之地-大纲合集实拍):大设定→小设定→技能条目 1234,任意深度
同类嵌套;装配/搜索等消费端按平铺条目工作,树仅是组织关系。
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402
from app.routers.l1 import (  # noqa: E402
    EntryIn, create_entry, delete_entry, list_entries, update_entry,
)


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    with tx() as conn:
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
    yield dbmod
    dbmod._conn = None


def _mk(name: str, parent: str | None = None, category: str = "worldview") -> str:
    return create_entry("p1", EntryIn(category=category, name=name,
                                      parent_entry_id=parent))["id"]


def test_free_depth_chain(tmp_db):
    """大设定→小设定→技能 1234:同类别任意深度链(用户大纲合集形态)。"""
    big = _mk("原初葬界")
    small = _mk("葬界·装备体系", parent=big)
    s1 = _mk("装备·头部", parent=small)
    s2 = _mk("装备·肩部", parent=small)
    listing = {e["id"]: e for e in list_entries("p1")["entries"]}
    assert listing[small]["parent_entry_id"] == big
    assert listing[s1]["parent_entry_id"] == small


def test_cross_category_parent_rejected(tmp_db):
    _mk("世界观节点", category="worldview")
    with tx() as conn:
        wid = conn.execute(
            "SELECT id FROM l1_entries WHERE category='worldview'").fetchone()[0]
    with pytest.raises(HTTPException, match="不一致"):
        create_entry("p1", EntryIn(category="character", name="角色子条目",
                                   parent_entry_id=wid))


def test_reparent_with_cycle_guard(tmp_db):
    a = _mk("甲")
    b = _mk("乙", parent=a)
    c = _mk("丙", parent=b)
    # 乙换父到顶层(提级)
    update_entry(b, {"parent_entry_id": None})
    listing = {e["id"]: e for e in list_entries("p1")["entries"]}
    assert listing[b]["parent_entry_id"] is None
    # 丙换父到甲 ✓
    update_entry(c, {"parent_entry_id": a})
    # 甲换父到丙 → 成环,拒绝
    with pytest.raises(HTTPException, match="成环"):
        update_entry(a, {"parent_entry_id": c})


def test_delete_cascades_subtree(tmp_db):
    big = _mk("大设定")
    small = _mk("小设定", parent=big)
    s1 = _mk("技能1", parent=small)
    s2 = _mk("技能2", parent=small)
    other = _mk("别家")
    r = delete_entry(big)
    assert r["deleted"] == 4   # 大设定+小设定+技能1+技能2
    left = {e["name"] for e in list_entries("p1")["entries"]}
    assert left == {"别家"} and s1 not in left


def test_tree_is_organization_only(tmp_db):
    """判据:树仅组织关系——挂不挂父,列表平铺含全部条目(消费端按平铺工作)。"""
    _mk("设定甲")
    _mk("设定乙", parent=_mk("设定父"))
    names = {e["name"] for e in list_entries("p1")["entries"]}
    assert names == {"设定甲", "设定乙", "设定父"}
