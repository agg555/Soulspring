// 与后端 schema 对应的类型定义(单文件薄前端,类型就近放)
export interface Project {
  id: string;
  name: string;
  genre: string | null;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Book extends Project {
  protagonist: string | null;
  tropes: string[];
  audience: string | null;
  style: string[];
  plot_mode: string | null;
  power_preset: string | null;
  cheat_preset: string | null;
  core_conflict: string | null;
  chapter_words: number | null;
  target_words: number | null;
}

export interface F0Options {
  [key: string]: unknown;
  小说类型: string[];
  核心设定流派: string[];
  受众定位: string[];
  风格偏好: string[];
  力量体系: Record<string, string[]>;
  金手指类型: string[];
  情节结构模式: { value: string; label: string; desc: string }[];
}

export interface L1Entry {
  id: string;
  project_id: string;
  category: string;
  name: string;
  fields: Record<string, string>;
  content: string;
  entry_status: "confirmed" | "proposal";
  source: string;
  created_at: string;
  updated_at: string;
}

export interface L1FieldDef {
  key: string;
  label: string;
  type: "text" | "textarea";
}

export interface L1Category {
  key: string;
  label: string;
  fields: L1FieldDef[];
}

export interface L1Schema {
  categories: L1Category[];
}

export type ChapterStatus =
  | "unwritten"
  | "draft"
  | "human_editing"
  | "final_review"
  | "finalized";

export interface OutlineNode {
  id: string;
  project_id: string;
  parent_id: string | null;
  kind: "category" | "volume" | "arc" | "chapter" | "scene";
  title: string;
  sort_order: number;
  status: ChapterStatus;
  status_label: string | null;
  status_changed_at: string | null;
  allowed_transitions: ChapterStatus[];
  summary?: string | null;
  note?: string | null;
  scene_fields?: Record<string, string>;
  created_at: string;
  updated_at: string;
}

// 场景五字段(C1 拍板,固定):键名与后端 SCENE_FIELDS 对齐
export interface SceneFields {
  goal: string;        // 场景目标
  conflict: string;    // 冲突
  hook: string;        // 出口钩子
  characters: string;  // 出场角色
  target_words: string;// 预计字数
}

export interface NodeDetail {
  node: OutlineNode & {
    children: { id: string; kind: OutlineNode["kind"]; title: string; sort_order: number; status: string }[];
    status_log: { from_status: string | null; to_status: string; changed_at: string; note: string | null }[];
    field_history: { field: string; before: string | null; after: string | null; source: string; created_at: string }[];
  };
}

export interface BranchSession {
  id: string;
  name: string;
  status: "active" | "archived";
  branch_payload: { title?: string; summary?: string; note?: string; scene_fields?: Partial<SceneFields> };
  created_at: string;
}

export interface StatusLogRow {
  from_status: string | null;
  to_status: string;
  changed_at: string;
}

export interface BuildResult {
  ok: boolean;
  run_id: string;
  count: number;
  parsed_raw: number;
  dropped: number;
  usage: UsageRow;
  warning?: string;
}

export interface AssemblySection {
  source: string;
  kind: "always" | "on_demand";
  title: string;
  content: string;
  included: boolean;
  trimmed_by_limit?: boolean;
  entry_id?: string;
}

export interface Assembly {
  node_id: string;
  sections: AssemblySection[];
  total_chars: number;
  limit_chars: number;
  over_limit: boolean;
  trimmed: boolean;
  plan: Record<string, unknown>;
}

export interface Validation {
  code: string;
  status: "passed" | "warning" | "failed";
  message: string;
  dimension?: string;
  suggestion?: string;
  auto_fixable?: boolean;
  evidence?: string;
  dismissed?: boolean;
  dismiss_note?: string;
}

export interface ChangesetView {
  id: string;
  node_id: string;
  status: string;
  validations: Validation[];
  review: Record<string, unknown> | null;
  task_spec: Record<string, unknown> | null;
  patches: {
    id: string;
    field: string;
    before: string | null;
    after: string | null;
    reason: string;
    version?: number;
  }[];
  patch_history?: PatchRow[];
  node_status: string;
  created_at: string;
  updated_at: string;
  last_calls?: { run_id: string; model: string; duration_ms: number }[];
  usage_total?: number;
}

export interface WorkbenchPreview {
  node: OutlineNode;
  plan: Record<string, unknown>;
  assembly: Assembly;
  current_text: string;
  revision: number;
  changeset: ChangesetView | null;
  skill_effective?: string;
  skill_override?: string | null;
  skill_global?: string;
  running_task?: GenTask | null;
}

export interface Overview {
  projects: Project[];
  today_cost: number;
  month_cost: number;
  today_calls: number;
}

export interface LlmSettings {
  provider_name: string;
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
}

export interface PriceEntry {
  model: string;
  input_per_m: number;
  output_per_m: number;
}

export interface PricingSettings {
  default: PriceEntry;
  models: PriceEntry[];
}

export interface BudgetSettings {
  per_chapter_alert: number;
  chat_turn_alert: number;
}

export interface AssemblySettings {
  token_limit: number | null;
}

// 思考档位:GLM 系模型强制思考且思考 token 按输出价计费,故按动作分档省预算
export type ThinkingLevel = "low" | "high" | "max";

export interface ThinkingSettings {
  enabled: boolean;
  model_match: string;
  default: ThinkingLevel;
  by_action: Record<string, ThinkingLevel>;
}

export interface Settings {
  llm: LlmSettings;
  pricing: PricingSettings;
  budget: BudgetSettings;
  assembly: AssemblySettings;
  thinking: ThinkingSettings;
  skills: SkillsSettings;
  mcp: McpSettings;
  outline: { scenes_enabled: boolean };
  api_key_set: boolean;
}

export interface UsageRow {
  id: string;
  run_id: string;
  model: string;
  action: string;
  request_tokens: number;
  response_tokens: number;
  cost_total: number;
  duration_ms: number;
  created_at: string;
}

// ── 生成任务(需求1)+ 技能(需求2/3)+ MCP 预留区(需求4)──

export type GenStage =
  | "queued" | "plan" | "draft" | "normalize" | "audit" | "review" | "repair"
  | "done" | "error";

export interface GenTask {
  id: string;
  project_id: string;
  node_id: string;
  node_title?: string;
  project_name?: string;
  kind: "draft" | "repair" | "chat";
  skill: string | null;
  session_id?: string | null;   // 对话任务关联的会话线
  stage: GenStage;
  status: "running" | "done" | "error";
  error: string | null;
  result: { changeset: ChangesetView | null; note: string | null; usage_total?: number } | null;
  usage_total: number | null;
  created_at: string;
  updated_at: string;
}

export interface SkillInfo {
  key: string;
  name: string;
  description: string;
}

export interface SkillsSettings {
  global_default: string;
  book_overrides: Record<string, string>;
}

export interface McpServer {
  name: string;
  transport?: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  enabled: boolean;
}

export interface McpSettings {
  servers: McpServer[];
  search_fallback?: string;
}

// ── 精修期第一批(A1/A2/A3/C5,执行书 2026-08-31)──

export interface PatchRow {
  id: string;
  changeset_id: string;
  target_type: string;
  target_id: string;
  field: string;
  before: string | null;
  after: string | null;
  reason: string;
  selected: number;
  applied_revision: number | null;
  version: number;
  created_at: string | null;
}

export interface SuggestionTarget {
  node_id?: string;
  field?: string;
  value?: string;
  revised_text?: string;
  [key: string]: unknown;
}

// Suggestion target_type 扩展(第三批 E)
export interface Suggestion {
  quote: string;
  issue: string;
  suggestion: string;
  severity: string;
  target_type: string;   // none | chapter_text | outline_field | event_field | relation_field
  target: SuggestionTarget;
  adopted?: boolean;
  adopted_at?: string;
  adopt_summary?: string;
}

export interface ChatMessageMeta {
  skill?: string | null;
  model?: string;
  cost?: number;
  suggestions?: Suggestion[];
  parse_error?: boolean;
  attachments?: { type: string; id?: string | null; label: string }[];
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  meta: ChatMessageMeta | null;
  created_at: string;
}

export interface ConversationSession {
  id: string;
  project_id: string | null;
  owner_type: "review" | "chat_test" | "outline_node" | "branch";
  owner_id: string;
  name: string;
  created_at: string;
  message_count: number;
  last_message_at: string | null;
  status?: "active" | "archived";
  branch_payload?: BranchSession["branch_payload"];
}

export interface AttachmentRef {
  type: "chapter" | "entry" | "hook";
  id?: string | null;
  label: string;
}

export interface ChatRefs {
  chapters: { id: string; title: string; status: string }[];
  entries: { id: string; category: string; name: string }[];
  hooks: { detail: string; status: string; planted_chapter: number }[];
}

// ── 第三批(任务词 2026-09-01)──

export interface QualityParts {
  review_score: number | null;
  zhuque_score: number | null;
  cost: number;
  cost_score: number;
  critical: number;
  score: number | null;
  veto: boolean;
}

export interface DashboardRow {
  node_id: string;
  title: string;
  status: string;
  status_label: string;
  words: number;
  critical: number;
  warning: number;
  review: { scores?: Record<string, { score: number }>; findings?: unknown[] } | null;
  zhuque_human: number | null;
  cost: number;
  last_stage: string | null;
  last_stage_at: string | null;
  quality: QualityParts;
}

export interface DashboardData {
  chapters: DashboardRow[];
  weights: { w_review: number; w_zhuque: number; w_cost: number };
  alert: number;
  status_labels: Record<string, string>;
}

export interface ProductionEvent {
  kind: string;
  at: string;
  ended_at?: string;
  detail: string;
}

export interface WordStats {
  today: { human: number; ai: number };
  hour: { human: number; ai: number };
  chapter: { human: number; ai: number };
  last24h: { hour: string; human: number; ai: number }[];
  week: { day: string; human: number; ai: number }[];
  since: { human: number; ai: number };
  now: string;
}

export interface TimelineEvent {
  id: string;
  project_id: string;
  time_label: string;
  title: string;
  summary: string;
  line: "主线" | "支线";
  status: "已定" | "未定";
  sort_key: number;
  created_at: string;
  updated_at: string;
  chapters: { id: string; title: string; status: string; status_label?: string }[];
  all_chapters?: { id: string; title: string; status: string }[];
  field_history?: { field: string; before: string | null; after: string | null; source: string; created_at: string }[];
}

export interface CharacterRelation {
  id: string;
  project_id: string;
  from_entry_id: string;
  to_entry_id: string;
  relation: string;
  kind: string;
  created_at: string;
  from_name?: string;
  to_name?: string;
}

// ── 第四批:统一图谱引擎(任务词 2026-09-01)──

export interface GraphBoard {
  id: string;
  project_id: string;
  kind: string;   // character|event|item|map|faction|hook|power|free|worldview
  name: string;
  grid_on: number;
  created_at: string;
  updated_at: string;
  node_count?: number;
  edge_count?: number;
}

export interface GraphNode {
  id: string;
  board_id: string;
  ref_type: "l1_entry" | "timeline_event" | "free";
  ref_id: string | null;
  label: string;
  sub_label: string | null;
  x: number;
  y: number;
  style: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  board_id: string;
  from_node_id: string;
  to_node_id: string;
  label: string;
  kind: string;
}
