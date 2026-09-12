"""批次七⑥:模板双层回归(存→选→套闭环 + 预设题材包 + 分组列表)。

判据对齐执行书④:存→选→套闭环(节点/清单完整还原);预设与用户模板分组
显示;AI 起草无直写通道(架构保证,模板路由只提供人操作端点)。
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import tx  # noqa: E402
from app.graph_presets import PRESET_PACKS  # noqa: E402
from app.routers.graphs import (  # noqa: E402
    BoardIn, EdgeIn, NodeIn, NodePatch, board_detail, create_board, create_edge,
    create_node, patch_node,
)
from app.routers.templates import (  # noqa: E402
    ApplyIn, SaveIn, apply_pack, apply_template, delete_template, list_templates,
    save_template,
)


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    with tx() as conn:   # 种子书:图板/模板套用都挂 p1
        conn.execute("INSERT INTO projects(id, name, created_at, updated_at)"
                     " VALUES('p1', '测试书', '2026-09-01', '2026-09-01')")
    yield dbmod
    dbmod._conn = None


def _mk_board(kind: str = "free", name: str = "草稿板") -> str:
    return create_board("p1", BoardIn(kind=kind, name=name))["board"]["id"]


def _add_node(bid: str, label: str, x: int, y: int, style: dict | None = None) -> str:
    nn = create_node(bid, NodeIn(label=label, ref_type="free", x=x, y=y))
    if style:
        patch_node(nn["node"]["id"], NodePatch(style=style))
    return nn["node"]["id"]


def test_save_apply_roundtrip_restores_nodes_checklists_edges(tmp_db):
    bid = _mk_board()
    _add_node(bid, "金手指设定", 60, 60, {"card": "checklist",
                                          "items": [{"text": "规则", "done": False},
                                                    {"text": "代价", "done": False}]})
    _add_node(bid, "主线钩子", 280, 60)
    _add_node(bid, "卷检查单", 60, 280, {"card": "checklist",
                                         "items": [{"text": "伏笔对齐", "done": False}]})
    r = save_template(SaveIn(name="我的主控板", board_id=bid))
    assert r["ok"] and r["node_count"] == 3
    # 套用到新板:节点/清单完整还原(判据)
    out = apply_template(r["id"], ApplyIn(pid="p1", name="套用板"))
    view = board_detail(out["board"]["id"])
    assert view["board"]["name"] == "套用板"
    assert {n["label"] for n in view["nodes"]} == {"金手指设定", "主线钩子", "卷检查单"}
    checklist = [n for n in view["nodes"] if n["style"].get("card") == "checklist"]
    assert len(checklist) == 2
    assert checklist[0]["style"]["items"][0]["text"] == "规则"
    # 连线还原:补一条边再存一版
    create_edge(out["board"]["id"],
                EdgeIn(from_node_id=view["nodes"][0]["id"],
                       to_node_id=view["nodes"][1]["id"], label="配合", kind="同盟"))
    r2 = save_template(SaveIn(name="带连线版", board_id=out["board"]["id"]))
    out2 = apply_template(r2["id"], ApplyIn(pid="p1"))
    view2 = board_detail(out2["board"]["id"])
    assert len(view2["edges"]) == 1 and view2["edges"][0]["label"] == "配合"


def test_ref_nodes_downgrade_to_free_in_template(tmp_db):
    bid = _mk_board()
    with tx() as conn:
        conn.execute("INSERT INTO l1_entries(id, project_id, category, name, content,"
                     " entry_status, created_at, updated_at)"
                     " VALUES('e1','p1','character','林凡','','confirmed',"
                     "'2026-09-01','2026-09-01')")
    create_node(bid, NodeIn(label="林凡", ref_type="l1_entry", ref_id="e1", x=10, y=10))
    r = save_template(SaveIn(name="人物骨架", board_id=bid))
    out = apply_template(r["id"], ApplyIn(pid="p1"))
    view = board_detail(out["board"]["id"])
    assert view["nodes"][0]["ref_type"] == "free"     # ref 丢弃(跨书不可移植)
    assert view["nodes"][0]["label"] == "林凡"         # 标签保留


def test_preset_and_user_grouped_listing(tmp_db):
    listing = list_templates()
    assert {p["key"] for p in listing["presets"]} >= {"urban", "xuanhuan", "systemflow"}
    assert listing["user"] == []
    bid = _mk_board()
    _add_node(bid, "自由卡", 10, 10)
    save_template(SaveIn(name="我的模板", board_id=bid))
    listing2 = list_templates()
    assert [u["name"] for u in listing2["user"]] == ["我的模板"]
    assert listing2["presets"]        # 两组并存(判据:分组显示)


def test_pack_apply_creates_all_boards(tmp_db):
    out = apply_pack("urban", ApplyIn(pid="p1"))
    assert len(out["boards"]) == len(PRESET_PACKS["urban"]["boards"])
    kinds = {b["kind"] for b in out["boards"]}
    assert "character" in kinds and "free" in kinds
    for b in out["boards"]:
        assert len(board_detail(b["id"])["nodes"]) > 0
    # 系统流包含清单卡(系统规则清单)
    sysp = apply_pack("systemflow", ApplyIn(pid="p1"))
    checklists = [n for b in sysp["boards"] for n in board_detail(b["id"])["nodes"]
                  if n["style"].get("card") == "checklist"]
    assert any(n["label"] == "系统规则清单" for n in checklists)


def test_delete_and_validation(tmp_db):
    bid = _mk_board()
    with pytest.raises(Exception):
        save_template(SaveIn(name="空板", board_id=bid))   # 空板拒绝
    _add_node(bid, "有内容", 10, 10)
    r = save_template(SaveIn(name="可删", board_id=bid))
    assert delete_template(r["id"])["ok"]
    with pytest.raises(Exception):
        apply_template(r["id"], ApplyIn(pid="p1"))
    with pytest.raises(Exception):
        apply_pack("不存在", ApplyIn(pid="p1"))
