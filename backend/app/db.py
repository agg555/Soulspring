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

_lock = threading.Lock()        # 写事务串行(tx 整段持有;非重入,get_conn 勿用)
_init_lock = threading.Lock()   # _conn 惰性初始化专用(短临界区)
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    """进程内单连接(SQLite 单用户场景足够),check_same_thread 关闭 + 自管锁。

    初始化必须持 _init_lock:备份守护线程(app/backup.py)与首个使用者可能并发
    撞进 "_conn is None" 分支,无锁会建出两条连接、后赋值者覆盖全局——先建连接
    的持有者(如测试 fixture 的 tmp 连接)被换成另一条库,测试表现为间歇
    UNIQUE 失败,严重时测试静默连上生产库(2026-09-12 深查实锤并修复)。
    """
    global _conn
    if _conn is None:
        with _init_lock:
            if _conn is None:   # 双检:等锁期间可能已被并发线程建好
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(DB_PATH, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                _conn = conn
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


# Mimosa 高危整改(2026-09-06):迁移加列登记制——(表,列)→完整字面 ALTER 语句。
# 标识符不可参数化,故新迁移场景必须在此登记完整字面语句,执行处零拼接。
_MIGRATION_COLUMNS: dict[tuple[str, str], str] = {
    ("projects", "protagonist"): "ALTER TABLE projects ADD COLUMN protagonist TEXT",
    ("projects", "tropes"): "ALTER TABLE projects ADD COLUMN tropes TEXT",
    ("projects", "audience"): "ALTER TABLE projects ADD COLUMN audience TEXT",
    ("projects", "style"): "ALTER TABLE projects ADD COLUMN style TEXT",
    ("projects", "plot_mode"): "ALTER TABLE projects ADD COLUMN plot_mode TEXT",
    ("projects", "power_preset"): "ALTER TABLE projects ADD COLUMN power_preset TEXT",
    ("projects", "cheat_preset"): "ALTER TABLE projects ADD COLUMN cheat_preset TEXT",
    ("projects", "core_conflict"): "ALTER TABLE projects ADD COLUMN core_conflict TEXT",
    ("projects", "chapter_words"): "ALTER TABLE projects ADD COLUMN chapter_words INTEGER",
    ("projects", "target_words"): "ALTER TABLE projects ADD COLUMN target_words INTEGER",
    ("l1_entries", "fields"): "ALTER TABLE l1_entries ADD COLUMN fields TEXT NOT NULL DEFAULT '{}'",
    ("l1_entries", "presence"): "ALTER TABLE l1_entries ADD COLUMN presence TEXT NOT NULL DEFAULT 'on_demand'",
    ("changesets", "base_revision"): "ALTER TABLE changesets ADD COLUMN base_revision INTEGER NOT NULL DEFAULT 0",
    ("changesets", "validations"): "ALTER TABLE changesets ADD COLUMN validations TEXT NOT NULL DEFAULT '[]'",
    ("changesets", "snapshot"): "ALTER TABLE changesets ADD COLUMN snapshot TEXT",
    ("changesets", "task_spec"): "ALTER TABLE changesets ADD COLUMN task_spec TEXT",
    ("changesets", "review"): "ALTER TABLE changesets ADD COLUMN review TEXT",
    ("changesets", "updated_at"): "ALTER TABLE changesets ADD COLUMN updated_at TEXT",
    ("l4_texts", "revision"): "ALTER TABLE l4_texts ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",
    ("l3_status_log", "note"): "ALTER TABLE l3_status_log ADD COLUMN note TEXT",
    ("zhuque_log", "segments"): "ALTER TABLE zhuque_log ADD COLUMN segments TEXT NOT NULL DEFAULT '[]'",
    ("changeset_patches", "version"): "ALTER TABLE changeset_patches ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ("changeset_patches", "created_at"): "ALTER TABLE changeset_patches ADD COLUMN created_at TEXT",
    ("review_messages", "session_id"): "ALTER TABLE review_messages ADD COLUMN session_id TEXT",
    ("gen_tasks", "session_id"): "ALTER TABLE gen_tasks ADD COLUMN session_id TEXT",
    ("outline_nodes", "summary"): "ALTER TABLE outline_nodes ADD COLUMN summary TEXT",
    ("outline_nodes", "note"): "ALTER TABLE outline_nodes ADD COLUMN note TEXT",
    ("outline_nodes", "scene_fields"): "ALTER TABLE outline_nodes ADD COLUMN scene_fields TEXT NOT NULL DEFAULT '{}'",
    ("conversation_sessions", "branch_payload"): "ALTER TABLE conversation_sessions ADD COLUMN branch_payload TEXT",
    ("conversation_sessions", "status"): "ALTER TABLE conversation_sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
    ("conversation_sessions", "digest"): "ALTER TABLE conversation_sessions ADD COLUMN digest TEXT NOT NULL DEFAULT ''",
    ("outline_field_history", "node_type"): "ALTER TABLE outline_field_history ADD COLUMN node_type TEXT NOT NULL DEFAULT 'node'",
    ("ai_usage_logs", "cached_tokens"): "ALTER TABLE ai_usage_logs ADD COLUMN cached_tokens INTEGER NOT NULL DEFAULT 0",
    ("graph_edges", "style"): "ALTER TABLE graph_edges ADD COLUMN style TEXT NOT NULL DEFAULT '{}'",
    ("l1_entries", "parent_entry_id"): "ALTER TABLE l1_entries ADD COLUMN parent_entry_id TEXT",
    ("outline_nodes", "body"): "ALTER TABLE outline_nodes ADD COLUMN body TEXT NOT NULL DEFAULT ''",
}


def _add_column(conn: sqlite3.Connection, table: str, col_def: str) -> None:
    """幂等加列:SQLite DDL 隐式提交,迁移必须容忍半执行状态。

    只允许 _MIGRATION_COLUMNS 登记过的(表,列),DDL 必须与登记逐字一致;
    幂等检查走 pragma_table_info 参数绑定。
    """
    col_name = col_def.split()[0]
    stmt = _MIGRATION_COLUMNS.get((table, col_name))
    if stmt is None or not stmt.endswith(col_def):
        raise ValueError(f"未登记的迁移加列: {table!r}/{col_def!r}(请在 _MIGRATION_COLUMNS 登记字面语句)")
    cols = {r[0] for r in conn.execute(
        "SELECT name FROM pragma_table_info(?)", (table,)).fetchall()}
    if col_name not in cols:
        conn.execute(stmt)


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
            # 角色关系一次性迁入统一引擎;旧表保留只读作对照(v10 语义冻结;
            # API 读链已下线,2026-09-06 审计 S2)
            migrate_character_relations_to_graph(conn)
            conn.execute("PRAGMA user_version = 11")
        if version < 12:
            # 批次二速赢:缓存命中记账(体感 2026-09-05"上下文用量+命中/未命中率")
            _add_column(conn, "ai_usage_logs", "cached_tokens INTEGER NOT NULL DEFAULT 0")
            conn.execute("PRAGMA user_version = 12")
        if version < 13:
            # 批次二图谱板扩展:边样式列(人物关系时间轴 at_chapter 等语义挂载点)
            _add_column(conn, "graph_edges", "style TEXT NOT NULL DEFAULT '{}'")
            conn.execute("PRAGMA user_version = 13")
        if version < 14:
            # 审计 2026-09-06 E区遗留:changeset_patches.created_at 收紧 NOT NULL。
            # v3 建表无此列、v8 才加列,之间存量行为 NULL;SQLite 改不了列约束,整表重建。
            _tighten_changeset_patches(conn)
            conn.execute("PRAGMA user_version = 14")
        if version < 15:
            # 批次三①:文本导入提案(拆书官第二模式;整批一条,批准后才落大纲/正文)
            conn.execute("""CREATE TABLE IF NOT EXISTS text_import_jobs (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id),
  source_name   TEXT NOT NULL DEFAULT '',
  target        TEXT NOT NULL DEFAULT 'outline',
  volume_id     TEXT,
  chapters      TEXT NOT NULL DEFAULT '[]',
  warnings      TEXT NOT NULL DEFAULT '[]',
  status        TEXT NOT NULL DEFAULT 'awaiting_approval',
  decided_at    TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 15")
        if version < 16:
            # 批次三⑤上下文经济:"前情提要"存会话行(纯算法压缩,原文全留库)
            _add_column(conn, "conversation_sessions", "digest TEXT NOT NULL DEFAULT ''")
            conn.execute("PRAGMA user_version = 16")
        if version < 17:
            # 批次七②:分层搜索——FTS5 trigram 虚拟表(中文子串免分词)+触发器随写随更。
            # 索引范围=章节正文(l4)/档案条目(l1 name+content)/大纲(title+summary)/
            # 时间线(title+summary);UNINDEXED 列承载过滤与跳转元数据。
            # 1-2 字短查 trigram 物理不命中(至少 3 字符),由查询侧回退 LIKE 兜底
            # (见 routers/search.py),本迁移只管索引本体。
            conn.executescript("""
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
  title, content,
  group_kind UNINDEXED,
  ref_id UNINDEXED,
  project_id UNINDEXED,
  tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS search_l4_ai AFTER INSERT ON l4_texts BEGIN
  DELETE FROM search_index WHERE group_kind='chapter' AND ref_id=NEW.node_id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    SELECT COALESCE(n.title,''), COALESCE(NEW.content,''),
           'chapter', NEW.node_id, n.project_id
    FROM outline_nodes n WHERE n.id=NEW.node_id
      AND COALESCE(NEW.content,'') != '';
END;
CREATE TRIGGER IF NOT EXISTS search_l4_au AFTER UPDATE ON l4_texts BEGIN
  DELETE FROM search_index WHERE group_kind='chapter' AND ref_id=NEW.node_id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    SELECT COALESCE(n.title,''), COALESCE(NEW.content,''),
           'chapter', NEW.node_id, n.project_id
    FROM outline_nodes n WHERE n.id=NEW.node_id
      AND COALESCE(NEW.content,'') != '';
END;
CREATE TRIGGER IF NOT EXISTS search_l4_ad AFTER DELETE ON l4_texts BEGIN
  DELETE FROM search_index WHERE group_kind='chapter' AND ref_id=OLD.node_id;
END;
CREATE TRIGGER IF NOT EXISTS search_l1_ai AFTER INSERT ON l1_entries BEGIN
  DELETE FROM search_index WHERE group_kind='entry' AND ref_id=NEW.id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    VALUES(COALESCE(NEW.name,''), COALESCE(NEW.content,''),
           'entry', NEW.id, NEW.project_id);
END;
CREATE TRIGGER IF NOT EXISTS search_l1_au AFTER UPDATE ON l1_entries BEGIN
  DELETE FROM search_index WHERE group_kind='entry' AND ref_id=NEW.id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    VALUES(COALESCE(NEW.name,''), COALESCE(NEW.content,''),
           'entry', NEW.id, NEW.project_id);
END;
CREATE TRIGGER IF NOT EXISTS search_l1_ad AFTER DELETE ON l1_entries BEGIN
  DELETE FROM search_index WHERE group_kind='entry' AND ref_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS search_outline_ai AFTER INSERT ON outline_nodes BEGIN
  DELETE FROM search_index WHERE group_kind='outline' AND ref_id=NEW.id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    VALUES(COALESCE(NEW.title,''), COALESCE(NEW.summary,''),
           'outline', NEW.id, NEW.project_id);
END;
CREATE TRIGGER IF NOT EXISTS search_outline_au AFTER UPDATE ON outline_nodes BEGIN
  DELETE FROM search_index WHERE group_kind='outline' AND ref_id=NEW.id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    VALUES(COALESCE(NEW.title,''), COALESCE(NEW.summary,''),
           'outline', NEW.id, NEW.project_id);
END;
CREATE TRIGGER IF NOT EXISTS search_outline_ad AFTER DELETE ON outline_nodes BEGIN
  DELETE FROM search_index WHERE group_kind='outline' AND ref_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS search_tl_ai AFTER INSERT ON timeline_events BEGIN
  DELETE FROM search_index WHERE group_kind='timeline' AND ref_id=NEW.id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    VALUES(COALESCE(NEW.title,''), COALESCE(NEW.summary,''),
           'timeline', NEW.id, NEW.project_id);
END;
CREATE TRIGGER IF NOT EXISTS search_tl_au AFTER UPDATE ON timeline_events BEGIN
  DELETE FROM search_index WHERE group_kind='timeline' AND ref_id=NEW.id;
  INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
    VALUES(COALESCE(NEW.title,''), COALESCE(NEW.summary,''),
           'timeline', NEW.id, NEW.project_id);
END;
CREATE TRIGGER IF NOT EXISTS search_tl_ad AFTER DELETE ON timeline_events BEGIN
  DELETE FROM search_index WHERE group_kind='timeline' AND ref_id=OLD.id;
END;
""")
            # 存量回填(迁移时刻的全部在库内容)
            conn.execute("""
INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
  SELECT n.title, COALESCE(l.content,''), 'chapter', n.id, n.project_id
  FROM l4_texts l JOIN outline_nodes n ON n.id = l.node_id
  WHERE COALESCE(l.content,'') != ''""")
            conn.execute("""
INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
  SELECT COALESCE(name,''), COALESCE(content,''), 'entry', id, project_id
  FROM l1_entries""")
            conn.execute("""
INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
  SELECT COALESCE(title,''), COALESCE(summary,''), 'outline', id, project_id
  FROM outline_nodes""")
            conn.execute("""
INSERT INTO search_index(title, content, group_kind, ref_id, project_id)
  SELECT COALESCE(title,''), COALESCE(summary,''), 'timeline', id, project_id
  FROM timeline_events""")
            conn.execute("PRAGMA user_version = 17")
        if version < 18:
            # 批次七③:工具调用过程实时显示——任务步骤明细表(底稿 B① 薄实现,
            # 兼容 A4 轮询不加 SSE):每环节一行(名称/工具/参数摘要/状态/起止/产物摘要),
            # 轮询返回体经 task_view 附带 steps,任务卡展开即时间线。
            conn.execute("""CREATE TABLE IF NOT EXISTS gen_task_steps (
  id          TEXT PRIMARY KEY,
  task_id     TEXT NOT NULL REFERENCES gen_tasks(id),
  seq         INTEGER NOT NULL,
  name        TEXT NOT NULL,
  tool        TEXT NOT NULL DEFAULT '',
  params      TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'running',
  artifact    TEXT NOT NULL DEFAULT '',
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  duration_ms INTEGER
)""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gen_task_steps_task"
                " ON gen_task_steps(task_id, seq)")
            conn.execute("PRAGMA user_version = 18")
        if version < 19:
            # 批次七⑥:模板双层(预设题材包+用户模板)——用户模板入库(预设为代码
            # 常量,零迁移);payload=板级 JSON(nodes+edges 临时下标引用),套用即还原。
            conn.execute("""CREATE TABLE IF NOT EXISTS templates (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'free',
  note        TEXT NOT NULL DEFAULT '',
  payload     TEXT NOT NULL DEFAULT '{}',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 19")
        if version < 20:
            # 批次七⑤:构思树——idea_nodes 轻表(建议块/奇思妙想下钻子讨论)。
            # 三态 status=open 待议/adopted 采纳(标记共识,写回仍走采纳闸门)/
            # dropped 放弃(冻结不喂 AI);depth 根=1 上限 3;source_ref=来源建议
            # (会话/消息/序号 JSON);子讨论=conversation_sessions.owner_type='idea'。
            conn.execute("""CREATE TABLE IF NOT EXISTS idea_nodes (
  id             TEXT PRIMARY KEY,
  project_id     TEXT NOT NULL REFERENCES projects(id),
  parent_idea_id TEXT REFERENCES idea_nodes(id),
  title          TEXT NOT NULL,
  note           TEXT NOT NULL DEFAULT '',
  status         TEXT NOT NULL DEFAULT 'open',
  depth          INTEGER NOT NULL DEFAULT 1,
  source_ref     TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
)""")
            conn.execute("PRAGMA user_version = 20")
        if version < 21:
            # 批次甲:L1 档案库树形化——条目可挂父条目(同类别内自由层级,
            # 大设定→小设定→技能条目;用户大纲合集实拍形态)。组织关系,零消费语义变更。
            _add_column(conn, "l1_entries", "parent_entry_id TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_l1_parent ON l1_entries(parent_entry_id)")
            conn.execute("PRAGMA user_version = 21")
        if version < 22:
            # WPS 式大纲(任务词 2026-09-09):节点正文列(所有 kind 可有,
            # WPS 式"标题+正文段";章的正文仍走 l4,body 服务卷/总纲/子题)。
            # 老书零迁移成本:默认空串,装配注入由 settings.assembly.body_inject 控制(默认关)。
            _add_column(conn, "outline_nodes", "body TEXT NOT NULL DEFAULT ''")
            conn.execute("PRAGMA user_version = 22")


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


def _tighten_changeset_patches(conn: sqlite3.Connection) -> None:
    """v14:changeset_patches.created_at 收紧 NOT NULL(审计 2026-09-06,原 E 区遗留)。

    SQLite 不能改列约束,整表重建。DDL 隐式提交,故各步幂等可重入:新表建前先查
    sqlite_master,回填 INSERT OR IGNORE 按主键去重,换名放最后——任何一步半执行后
    重跑本函数都不丢行、不重复。列结构与原表逐列一致,仅 created_at 收紧为
    NOT NULL DEFAULT ''(历史空值回填空串,前端版本历史按空显示)。
    抽成函数供测试直接触发(同 migrate_character_relations_to_graph 先例)。
    """
    old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='changeset_patches'"
    ).fetchone() is not None
    new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table'"
        " AND name='changeset_patches_tighten'"
    ).fetchone() is not None
    if old:
        if not new:
            conn.execute("""CREATE TABLE changeset_patches_tighten (
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
  created_at        TEXT NOT NULL DEFAULT ''
)""")
        conn.execute(
            "INSERT OR IGNORE INTO changeset_patches_tighten"
            " (id, changeset_id, target_type, target_id, field, before_hash,"
            "  expected_revision, anchor, before, after, reason, selected,"
            "  applied_revision, version, created_at)"
            " SELECT id, changeset_id, target_type, target_id, field, before_hash,"
            "  expected_revision, anchor, before, after, reason, selected,"
            "  applied_revision, version, COALESCE(created_at,'')"
            " FROM changeset_patches")
        conn.execute("DROP TABLE changeset_patches")
        new, old = True, False
    if new and not old:
        conn.execute("ALTER TABLE changeset_patches_tighten RENAME TO changeset_patches")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
