"""批次四⑤:千章性能压测(执行书 §1⑤)——临时库造 1400 章数据集,实测四个读路径耗时。

数据说话,不凭预言上虚拟滚动;结果抄录执行书 §5。只动 tmp 库,运行库零接触。
"""
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.db as dbmod  # noqa: E402

tmp = tempfile.mkdtemp()
dbmod.DATA_DIR = Path(tmp)
dbmod.DB_PATH = Path(tmp) / "stress.db"
dbmod._conn = None
dbmod.migrate()

NOW = datetime.now(timezone.utc).isoformat()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed() -> str:
    pid = f"proj_{uuid.uuid4().hex[:12]}"
    volumes, chapters = 20, 1400
    with dbmod.tx() as conn:
        conn.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                     (pid, "千章压测书", now(), now()))
        for v in range(volumes):
            vid = f"on_v{v}"
            conn.execute(
                "INSERT INTO outline_nodes(id,project_id,parent_id,kind,title,created_at,"
                "updated_at) VALUES(?,?,NULL,'volume',?,?,?)",
                (vid, pid, f"第{v + 1}卷", now(), now()))
            for c in range(chapters // volumes):
                cid = f"on_c{v}_{c}"
                conn.execute(
                    "INSERT INTO outline_nodes(id,project_id,parent_id,kind,title,created_at,"
                    "updated_at) VALUES(?,?,?,?,?,?,?)",
                    (cid, pid, vid, "chapter", f"第{v + 1}卷第{c + 1}章", now(), now()))
                conn.execute(
                    "INSERT INTO l4_texts(node_id,content,updated_at) VALUES(?,?,?)",
                    (cid, f"第{v + 1}卷第{c + 1}章正文。" * 200, now()))
        # L1 六类各 50 条 + hook 板 300 节点 200 边(图谱重负载)
        for i in range(300):
            conn.execute(
                "INSERT INTO l1_entries(id,project_id,category,name,content,entry_status,"
                "created_at,updated_at) VALUES(?,?,?,?,?,'confirmed',?,?)",
                (f"l1_{i}", pid, "character", f"角色{i:03d}", "设定内容。" * 30, now(), now()))
        conn.execute(
            "INSERT INTO graph_boards(id,project_id,kind,name,created_at,updated_at)"
            " VALUES('gb_stress',?,'character','压测关系板',?,?)", (pid, now(), now()))
        for i in range(300):
            conn.execute(
                "INSERT INTO graph_nodes(id,board_id,label,ref_type,ref_id,x,y,created_at,"
                "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (f"gn_{i}", "gb_stress", f"角色{i:03d}", "l1_entry", f"l1_{i}",
                 (i % 20) * 160.0, (i // 20) * 90.0, now(), now()))
        for i in range(299):
            conn.execute(
                "INSERT INTO graph_edges(id,board_id,from_node_id,to_node_id,label,kind,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"ge_{i}", "gb_stress", f"gn_{i}", f"gn_{i + 1}", "关系", "其他",
                 now(), now()))
    return pid


def bench(label: str, fn, rounds: int = 3) -> None:
    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    print(f"{label:<28} best={min(times):8.1f}ms  avg={sum(times) / len(times):8.1f}ms")


def main() -> None:
    from app.routers.chaishu import text_split  # noqa: F401  (确认导入链无碍)
    from app.routers.diagnostics import algorithm_check, graph_overview
    from app.routers.outline import list_nodes

    pid = seed()
    print(f"数据集:20 卷 / 1400 章(每章正文≈2400字)/ L1 300 条 / 图谱板 300 节点 299 边")
    bench("大纲树 list_nodes", lambda: list_nodes(pid))
    bench("算法体检 algorithm_check", lambda: algorithm_check(pid))
    bench("总览聚合 graph_overview", lambda: graph_overview(pid))
    bench("大纲树×2 复测", lambda: list_nodes(pid), rounds=5)


if __name__ == "__main__":
    main()
