"""SQLite 主存:连接管理与 schema 迁移。

约定:
- 单文件主存 data/soulspring.db(任务书 §3,git 跟踪作备份);
- 全部时间戳存 UTC ISO 字符串;
- 迁移用"建表 + user_version 步进",不引入重迁移框架。
"""
from __future__ import annotations

import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "soulspring.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    """进程内单连接(SQLite 单用户场景足够),check_same_thread 关闭 + 自管锁。"""
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


class tx:
    """写事务上下文:with tx() as conn: ..."""

    def __enter__(self) -> sqlite3.Connection:
        _lock.acquire()
        self.conn = get_conn()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            _lock.release()
        return False


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  genre       TEXT,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'active',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- L1 档案层(v1 六类 + 风格指纹特殊区;提案区 = entry_status='proposal')
CREATE TABLE IF NOT EXISTS l1_entries (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  category     TEXT NOT NULL,  -- worldview|character|power|faction|map|item_economy|style_fingerprint
  name         TEXT NOT NULL,
  content      TEXT NOT NULL,
  entry_status TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed|proposal
  source       TEXT NOT NULL DEFAULT 'manual',     -- manual|ai_proposal|import
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l1_project ON l1_entries(project_id, category);

-- L2 状态层(七类真相文件;草案区/回写审核 M4 演进)
CREATE TABLE IF NOT EXISTS l2_files (
  id         TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  file_type  TEXT NOT NULL,  -- current_state|resource_ledger|pending_hooks|chapter_summaries|subplot_board|emotional_arcs|character_matrix
  content    TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'official',  -- official|draft
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, file_type, status)
);

-- L3 进度层(大纲树:大类→卷→近纲→章;章节五态状态机)
CREATE TABLE IF NOT EXISTS outline_nodes (
  id                TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL REFERENCES projects(id),
  parent_id         TEXT REFERENCES outline_nodes(id),
  kind              TEXT NOT NULL,  -- category|volume|arc|chapter
  title             TEXT NOT NULL,
  sort_order        INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL DEFAULT 'unwritten',  -- unwritten|draft|human_editing|final_review|finalized
  status_changed_at TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outline_project ON outline_nodes(project_id, parent_id);

CREATE TABLE IF NOT EXISTS l3_status_log (
  id          TEXT PRIMARY KEY,
  node_id     TEXT NOT NULL REFERENCES outline_nodes(id),
  from_status TEXT,
  to_status   TEXT NOT NULL,
  changed_at  TEXT NOT NULL
);

-- L4 文本层(正式正文;AI 草稿先入 changesets,合入才落这里 + .md 镜像)
CREATE TABLE IF NOT EXISTS l4_texts (
  node_id    TEXT PRIMARY KEY REFERENCES outline_nodes(id),
  content    TEXT NOT NULL DEFAULT '',
  md_path    TEXT,
  updated_at TEXT NOT NULL
);

-- 变更集(chevoink ChangeSet 结构裁剪)
CREATE TABLE IF NOT EXISTS changesets (
  id         TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  node_id    TEXT REFERENCES outline_nodes(id),
  kind       TEXT NOT NULL DEFAULT 'draft',
  status     TEXT NOT NULL DEFAULT 'open',  -- open|applied|rejected
  payload    TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  decided_at TEXT
);

-- AgentRun(chevoink 结构裁剪:单用户,去 userId/关系表)
CREATE TABLE IF NOT EXISTS agent_runs (
  id             TEXT PRIMARY KEY,
  project_id     TEXT,
  node_id        TEXT,
  action         TEXT NOT NULL,
  agent_type     TEXT NOT NULL DEFAULT 'system',
  status         TEXT NOT NULL DEFAULT 'running',  -- running|succeeded|failed
  input_summary  TEXT,
  output_summary TEXT,
  error_message  TEXT,
  started_at     TEXT,
  finished_at    TEXT,
  created_at     TEXT NOT NULL
);

-- AiUsageLog(chevoink 结构 + 金额三字段,action 区分记账口径)
CREATE TABLE IF NOT EXISTS ai_usage_logs (
  id              TEXT PRIMARY KEY,
  run_id          TEXT REFERENCES agent_runs(id),
  project_id      TEXT,
  provider        TEXT NOT NULL DEFAULT '',
  model           TEXT NOT NULL DEFAULT '',
  action          TEXT NOT NULL,
  request_tokens  INTEGER,
  response_tokens INTEGER,
  cost_request    REAL NOT NULL DEFAULT 0,
  cost_response   REAL NOT NULL DEFAULT 0,
  cost_total      REAL NOT NULL DEFAULT 0,
  duration_ms     INTEGER NOT NULL DEFAULT 0,
  target_type     TEXT,
  target_id       TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_created ON ai_usage_logs(created_at);

-- 设置(KV,JSON value;api_key 不入库,走 data/secrets.local.json)
CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _add_column(conn: sqlite3.Connection, table: str, col_def: str) -> None:
    """幂等加列:SQLite DDL 隐式提交,迁移必须容忍半执行状态。"""
    col_name = col_def.split()[0]
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


def migrate() -> None:
    with tx() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            conn.executescript(SCHEMA_V1)
            conn.execute("PRAGMA user_version = 1")
        if version < 2:
            # M2:新建书向导扩列(F0)+ L1 条目结构化字段
            for col in (
                "protagonist TEXT",
                "tropes TEXT",
                "audience TEXT",
                "style TEXT",
                "plot_mode TEXT",
                "power_preset TEXT",
                "cheat_preset TEXT",
                "core_conflict TEXT",
                "chapter_words INTEGER",
                "target_words INTEGER",
            ):
                _add_column(conn, "projects", col)
            _add_column(conn, "l1_entries", "fields TEXT NOT NULL DEFAULT '{}'")
            conn.execute("PRAGMA user_version = 2")
        if version < 3:
            # M3:变更集完整契约(chevoink)+ 常驻/按需标记 + 计划卡 + 装配日志 + 乐观锁
            _add_column(conn, "l1_entries", "presence TEXT NOT NULL DEFAULT 'on_demand'")
            for col in ("base_revision INTEGER NOT NULL DEFAULT 0",
                        "validations TEXT NOT NULL DEFAULT '[]'",
                        "snapshot TEXT",
                        "task_spec TEXT",
                        "review TEXT",
                        "updated_at TEXT"):
                _add_column(conn, "changesets", col)
            conn.execute("UPDATE changesets SET status='draft' WHERE status='open'")
            conn.execute("UPDATE changesets SET status='failed' WHERE status='rejected'")
            _add_column(conn, "l4_texts", "revision INTEGER NOT NULL DEFAULT 1")
            conn.execute("""CREATE TABLE IF NOT EXISTS changeset_patches (
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
  applied_revision  INTEGER
)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS chapter_plans (
  node_id    TEXT PRIMARY KEY REFERENCES outline_nodes(id),
  plan       TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS assembly_logs (
  id          TEXT PRIMARY KEY,
  project_id  TEXT,
  node_id     TEXT,
  plan        TEXT,
  sections    TEXT NOT NULL DEFAULT '[]',
  total_chars INTEGER NOT NULL DEFAULT 0,
  limit_chars INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 3")
        if version < 4:
            # M4:审稿对话台 + 朱雀登记 + 状态机备注
            conn.execute("""CREATE TABLE IF NOT EXISTS review_messages (
  id          TEXT PRIMARY KEY,
  project_id  TEXT,
  node_id     TEXT,
  role        TEXT NOT NULL,
  content     TEXT NOT NULL,
  meta        TEXT,
  created_at  TEXT NOT NULL
)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS zhuque_log (
  id          TEXT PRIMARY KEY,
  project_id  TEXT,
  node_id     TEXT,
  verdict     TEXT NOT NULL,
  human_ratio REAL,
  suspect_ratio REAL,
  red_count   INTEGER,
  note        TEXT,
  created_at  TEXT NOT NULL
)""")
            _add_column(conn, "l3_status_log", "note TEXT")
            conn.execute("PRAGMA user_version = 4")
        if version < 5:
            # M5:朱雀登记扩展(红/黄/绿段位置,供 AI 分析对比;替代截图方案)+ 查证素材库
            _add_column(conn, "zhuque_log", "segments TEXT NOT NULL DEFAULT '[]'")
            conn.execute("""CREATE TABLE IF NOT EXISTS evidence_items (
  id          TEXT PRIMARY KEY,
  project_id  TEXT,
  query       TEXT NOT NULL,
  source      TEXT NOT NULL,
  url         TEXT,
  content     TEXT,
  confidence  REAL,
  created_at  TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 5")
        if version < 6:
            # M5:拆书官批量任务(600万字级:按 50 章/批分阶段拆,断点续跑)
            conn.execute("""CREATE TABLE IF NOT EXISTS chaishu_jobs (
  id            TEXT PRIMARY KEY,
  project_id    TEXT,
  book_title    TEXT NOT NULL,
  source_path   TEXT NOT NULL,
  output_dir    TEXT NOT NULL,
  total_chapters INTEGER NOT NULL DEFAULT 0,
  done_chapters INTEGER NOT NULL DEFAULT 0,
  batch_size    INTEGER NOT NULL DEFAULT 50,
  chapters      TEXT NOT NULL DEFAULT '[]',
  stage         TEXT NOT NULL DEFAULT 'summaries',
  status        TEXT NOT NULL DEFAULT 'ready',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 6")
        if version < 7:
            # 生成任务(需求稿 2026-08-31):草稿/AI自修 后台任务化,live 与 replay 同源;
            # 服务重启后 running 残留由读取端标记为 error(单用户,不做续跑)
            conn.execute("""CREATE TABLE IF NOT EXISTS gen_tasks (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL,
  node_id     TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'draft',
  skill       TEXT,
  stage       TEXT NOT NULL DEFAULT 'queued',
  status      TEXT NOT NULL DEFAULT 'running',
  error       TEXT,
  result      TEXT,
  usage_total REAL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 7")
        if version < 8:
            # 精修期第一批(执行书 2026-08-31):C5 版本历史 + A3 多线会话
            _add_column(conn, "changeset_patches", "version INTEGER NOT NULL DEFAULT 1")
            _add_column(conn, "changeset_patches", "created_at TEXT")
            conn.execute("""CREATE TABLE IF NOT EXISTS conversation_sessions (
  id         TEXT PRIMARY KEY,
  project_id TEXT,
  owner_type TEXT NOT NULL,               -- review|chat_test|outline_node|branch|
                                          -- timeline_event|relation|graph_node|graph_edge|graph_board
  owner_id   TEXT NOT NULL DEFAULT '',    -- 节点 id;全局型(测试对话)为空串
  name       TEXT NOT NULL,
  created_at TEXT NOT NULL
)""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_owner"
                " ON conversation_sessions(owner_type, owner_id)")
            _add_column(conn, "review_messages", "session_id TEXT")
            _add_column(conn, "gen_tasks", "session_id TEXT")
            # 节点摘要/备注(C2 预告列,执行书 §4):A1 轻档采纳的写回落点,本批先落列
            _add_column(conn, "outline_nodes", "summary TEXT")
            _add_column(conn, "outline_nodes", "note TEXT")
            # 存量审稿对话迁入会话制:每个 (project_id, node_id) 建一条"主讨论"线并回填
            rows = conn.execute(
                "SELECT DISTINCT project_id, node_id FROM review_messages"
                " WHERE session_id IS NULL").fetchall()
            for r in rows:
                node_id = r["node_id"] or ""
                name = "主讨论"
                if node_id:
                    nrow = conn.execute(
                        "SELECT title FROM outline_nodes WHERE id=?", (node_id,)).fetchone()
                    if nrow:
                        name = f"主讨论·{nrow['title']}"
                sid = f"conv_{uuid.uuid4().hex[:20]}"
                conn.execute(
                    "INSERT INTO conversation_sessions(id, project_id, owner_type, owner_id,"
                    " name, created_at) VALUES(?,?,?,?,?,?)",
                    (sid, r["project_id"], "review", node_id, name, _utcnow()))
                conn.execute(
                    "UPDATE review_messages SET session_id=? WHERE session_id IS NULL"
                    " AND COALESCE(project_id,'')=COALESCE(?,'')"
                    " AND COALESCE(node_id,'')=?",
                    (sid, r["project_id"], node_id))
            conn.execute("PRAGMA user_version = 8")
        if version < 9:
            # 精修期第二批(执行书 2026-08-31):C1 场景级 + C4 分支探索
            # 场景五字段 JSON(v8 漏列,本批补;仅 kind=scene 使用)
            _add_column(conn, "outline_nodes", "scene_fields TEXT NOT NULL DEFAULT '{}'")
            # 分支 = 特殊会话(owner_type='branch'):字段草稿包 + 结案状态
            _add_column(conn, "conversation_sessions", "branch_payload TEXT")
            _add_column(conn, "conversation_sessions", "status TEXT NOT NULL DEFAULT 'active'")
            # 大纲字段版本历史(C4 转正"原值进版本历史";A1 轻档采纳同款留痕)
            conn.execute("""CREATE TABLE IF NOT EXISTS outline_field_history (
  id         TEXT PRIMARY KEY,
  node_id    TEXT NOT NULL,
  field      TEXT NOT NULL,
  before     TEXT,
  after      TEXT,
  source     TEXT NOT NULL DEFAULT 'branch_promote',  -- branch_promote|suggestion_adopt|manual
  session_id TEXT,
  created_at TEXT NOT NULL
)""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_field_history_node"
                " ON outline_field_history(node_id, field)")
            conn.execute("PRAGMA user_version = 9")
        if version < 10:
            # 第三批(任务词 2026-09-01):码字统计 + 剧情时间线 + 角色关系图
            # 码字口径:人改保存=human;AI 草稿/自修/对话正文采纳=ai;回滚与合入不记
            # (合入只是把 patch.after 落 l4,不再算一次产量;重 roll 记 ai 覆盖前的净差)
            conn.execute("""CREATE TABLE IF NOT EXISTS word_count_log (
  id          TEXT PRIMARY KEY,
  project_id  TEXT,
  node_id     TEXT,
  source      TEXT NOT NULL DEFAULT 'human',  -- human|ai
  delta       INTEGER NOT NULL DEFAULT 0,     -- 相对上一版草稿的字数差(负=删)
  words_after INTEGER NOT NULL DEFAULT 0,     -- 该版总字数
  created_at  TEXT NOT NULL
)""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wordcount_created ON word_count_log(created_at)")
            # 剧情时间线(故事内容视角;与 B2 单章生产时间线不混装)
            conn.execute("""CREATE TABLE IF NOT EXISTS timeline_events (
  id         TEXT PRIMARY KEY,
  project_id TEXT,
  time_label TEXT NOT NULL DEFAULT '',    -- 如"第三个月"
  title      TEXT NOT NULL,
  summary    TEXT NOT NULL DEFAULT '',
  line       TEXT NOT NULL DEFAULT '主线',      -- 主线|支线
  status     TEXT NOT NULL DEFAULT '未定',      -- 已定|未定
  sort_key   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS event_chapters (
  event_id TEXT NOT NULL REFERENCES timeline_events(id),
  node_id  TEXT NOT NULL,
  PRIMARY KEY(event_id, node_id)
)""")
            # 角色关系图(引用 l1_entries category='character')
            conn.execute("""CREATE TABLE IF NOT EXISTS character_relations (
  id            TEXT PRIMARY KEY,
  project_id    TEXT,
  from_entry_id TEXT NOT NULL,
  to_entry_id   TEXT NOT NULL,
  relation      TEXT NOT NULL DEFAULT '',
  kind          TEXT NOT NULL DEFAULT '其他',      -- 亲情|爱情|友情|敌对|其他
  created_at    TEXT NOT NULL
)""")
            # 字段历史扩 node_type:区分 大纲节点/时间线事件/角色关系/图谱节点/图谱连线(采纳留痕同表)
            _add_column(conn, "outline_field_history", "node_type TEXT NOT NULL DEFAULT 'node'")
            conn.execute("PRAGMA user_version = 10")
        if version < 11:
            # 第四批(任务词 2026-09-01):统一图谱引擎 + 多类图谱板
            # 板 = kind 区分的同一引擎渲染;节点可 ref 既有对象(l1_entry/timeline_event)或自由建
            conn.execute("""CREATE TABLE IF NOT EXISTS graph_boards (
  id         TEXT PRIMARY KEY,
  project_id TEXT,
  kind       TEXT NOT NULL,               -- character|event|item|map|faction|hook|power|free|worldview
  name       TEXT NOT NULL,
  grid_on    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS graph_nodes (
  id        TEXT PRIMARY KEY,
  board_id  TEXT NOT NULL REFERENCES graph_boards(id),
  ref_type  TEXT NOT NULL DEFAULT 'free',  -- l1_entry|timeline_event|free
  ref_id    TEXT,
  label     TEXT NOT NULL,
  sub_label TEXT,
  x         REAL NOT NULL DEFAULT 0,
  y         REAL NOT NULL DEFAULT 0,
  style     TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS graph_edges (
  id          TEXT PRIMARY KEY,
  board_id    TEXT NOT NULL REFERENCES graph_boards(id),
  from_node_id TEXT NOT NULL,
  to_node_id   TEXT NOT NULL,
  label       TEXT NOT NULL DEFAULT '',
  kind        TEXT NOT NULL DEFAULT '其他',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)""")
            # 角色关系一次性迁入统一引擎;旧表保留只读作对照(v10 语义冻结)
            migrate_character_relations_to_graph(conn)
            conn.execute("PRAGMA user_version = 11")


def migrate_character_relations_to_graph(conn: sqlite3.Connection) -> None:
    """character_relations → graph_boards/nodes/edges(可重复调用:无行即空操作)。

    抽成函数供测试直接触发(v11 迁移只处理迁移时刻的存量)。
    """
    rels = conn.execute("SELECT * FROM character_relations").fetchall()
    if not rels:
        return
    bid = f"gb_{uuid.uuid4().hex[:20]}"
    now = _utcnow()
    conn.execute(
        "INSERT INTO graph_boards(id, project_id, kind, name, grid_on,"
        " created_at, updated_at) VALUES(?,?,?,?,1,?,?)",
        (bid, rels[0]["project_id"], "character", "人物关系图", now, now))
    node_map: dict[str, str] = {}

    def _mk_node(entry_id: str, idx: int) -> str:
        if entry_id in node_map:
            return node_map[entry_id]
        e = conn.execute(
            "SELECT name FROM l1_entries WHERE id=?", (entry_id,)).fetchone()
        ang = (idx / max(len(rels) * 2, 1)) * 2 * math.pi
        nid = f"gn_{uuid.uuid4().hex[:20]}"
        conn.execute(
            "INSERT INTO graph_nodes(id, board_id, ref_type, ref_id, label,"
            " sub_label, x, y, style, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (nid, bid, "l1_entry", entry_id,
             e["name"] if e else "(已删角色)", None,
             380 + 190 * math.cos(ang), 215 + 140 * math.sin(ang),
             "{}", now, now))
        node_map[entry_id] = nid
        return nid

    for i, r in enumerate(rels):
        a = _mk_node(r["from_entry_id"], i * 2)
        b = _mk_node(r["to_entry_id"], i * 2 + 1)
        conn.execute(
            "INSERT INTO graph_edges(id, board_id, from_node_id, to_node_id,"
            " label, kind, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (f"ge_{uuid.uuid4().hex[:20]}", bid, a, b,
             r["relation"], r["kind"], now, now))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
