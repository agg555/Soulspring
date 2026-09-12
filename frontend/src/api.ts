// 极薄 API 封装:同源 /api,错误统一抛中文可读消息
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      const d = body.detail ?? body;
      detail = typeof d === "string" ? d : JSON.stringify(d);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  overview: () => request<import("./types").Overview>("/api/overview"),
  createProject: (body: Partial<import("./types").Book>) =>
    request<{ id: string; name: string }>("/api/overview/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  options: () => request<import("./types").F0Options>("/api/books/options"),
  book: (pid: string) =>
    request<{
      book: import("./types").Book;
      l1_counts: Record<string, Record<string, number>>;
      outline_counts: Record<string, number>;
      skill_override?: string | null;
      skill_global?: string;
      skill_effective?: string;
    }>(`/api/books/${pid}`),
  updateBook: (pid: string, patch: Partial<import("./types").Book>) =>
    request<{ ok: boolean; book: import("./types").Book }>(`/api/books/${pid}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  l1List: (pid: string) =>
    request<{ entries: import("./types").L1Entry[]; style_fingerprint: import("./types").L1Entry[] }>(
      `/api/books/${pid}/l1`
    ),
  l1Schema: () =>
    request<import("./types").L1Schema>("/api/books/l1-schema"),
  l1Create: (
    pid: string,
    body: { category: string; name: string; fields: Record<string, string>; notes: string;
      parent_entry_id?: string | null }
  ) =>
    request(`/api/books/${pid}/l1`, { method: "POST", body: JSON.stringify(body) }),
  l1Update: (
    eid: string,
    patch: { name: string; fields: Record<string, string>; notes: string;
      parent_entry_id?: string | null }
  ) => request<import("./types").L1Entry>(`/api/l1/${eid}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  }),
  l1Approve: (eid: string) => request(`/api/l1/${eid}/approve`, { method: "POST" }),
  l1Delete: (eid: string) => request(`/api/l1/${eid}`, { method: "DELETE" }),
  llmPresets: () =>
    request<{ presets: { key: string; label: string; base_url: string; model: string;
      key_name: string; key_ready: boolean; active: boolean }[];
      current: { base_url: string; model: string } }>("/api/settings/llm-presets"),
  llmSwitch: (provider: string) =>
    request<{ ok: boolean; llm: { provider_name: string; base_url: string; model: string } }>(
      "/api/settings/llm-switch", { method: "POST", body: JSON.stringify({ provider }) }),
  // 二期⑧:温度预设三档(稳健/标准/灵感;一键切换即生效)
  temperaturePresets: () =>
    request<{ presets: { key: string; label: string; temperature: number;
      top_p: number | null; active: boolean }[]; current: { temperature: number; top_p: number | null } }>(
      "/api/settings/temperature-presets"),
  putTemperaturePreset: (key: string) =>
    request<{ ok: boolean; preset: { key: string; label: string; temperature: number; top_p: number | null } }>(
      "/api/settings/temperature-preset", { method: "PUT", body: JSON.stringify({ provider: key }) }),
  llmTest: () =>
    request<{ ok: boolean; model?: string; reply?: string; error?: string;
      tokens?: number[] }>("/api/settings/llm-test", { method: "POST" }),
  deleteConversation: (sid: string) =>
    request<{ ok: boolean }>(`/api/conversations/${sid}`, { method: "DELETE" }),
  buildProposeAsync: (pid: string) =>
    request<{ task: import("./types").GenTask }>(`/api/books/${pid}/build/propose-async`, {
      method: "POST",
    }),
  suggestField: (pid: string, body: { category: string; field: string; name?: string;
    known?: Record<string, string> }) =>
    request<{ text: string; cost: number }>(`/api/books/${pid}/build/suggest-field`, {
      method: "POST", body: JSON.stringify(body),
    }),
  outline: (pid: string) =>
    request<{ nodes: import("./types").OutlineNode[]; status_labels: Record<string, string> }>(
      `/api/books/${pid}/outline`
    ),
  // 批次三②:算法体检(六项纯规则检查,零 LLM 常驻;AI 体检=深度可选并存)
  algorithmCheck: (pid: string) =>
    request<{
      project_id: string;
      total_issues: number;
      checks: {
        key: string;
        title: string;
        count: number;
        items: { node_id: string; title: string; detail: string }[];
      }[];
    }>(`/api/books/${pid}/algorithm-check`),
  // 批次三①:文本导入(拆书官第二模式;纯算法切分,整批提案闸门)
  // 批次三⑥:全书总览图谱(聚合全部板,只读;数据同源=单板调整自动同步)
  graphOverview: (pid: string) =>
    request<{
      project_id: string;
      boards: {
        board_id: string; kind: string; name: string;
        nodes: { id: string; label: string; ref_type: string; ref_id: string | null;
          x: number; y: number; style: Record<string, unknown>; category: string }[];
        edges: { id: string; from_node_id: string; to_node_id: string;
          label: string; kind: string }[];
      }[];
      board_count: number; node_count: number; edge_count: number;
    }>(`/api/books/${pid}/graph-overview`),
  textSplit: (text: string) =>
    request<{
      chapters: { index: number; title: string; chars: number; content: string }[];
      warnings: string[];
      total_chars: number;
    }>("/api/chaishu/text-split", { method: "POST", body: JSON.stringify({ text }) }),
  textImportCreate: (body: {
    project_id: string; text: string; source_name: string;
    target: "outline" | "manuscript" | "l1"; volume_id?: string | null;
  }) =>
    request<{ mode: string; job_id?: string; count: number; message: string }>(
      "/api/chaishu/text-import", { method: "POST", body: JSON.stringify(body) }),
  textImports: (pid: string) =>
    request<{ jobs: { id: string; source_name: string; target: string;
      volume_id: string | null; status: string; created_at: string; count: number;
      titles: string[]; warnings: string[] }[] }>(
      `/api/chaishu/text-imports?project_id=${pid}`),
  textImportApprove: (jid: string, body: { volume_id?: string | null }) =>
    request<{ ok: boolean; created: number }>(
      `/api/chaishu/text-imports/${jid}/approve`, { method: "POST", body: JSON.stringify(body) }),
  // 批次四③:书=目录工作区(全书 md 镜像,DB 唯一真源)
  mirrorBook: (pid: string) =>
    request<{ ok: boolean; dir: string; files: number }>(`/api/books/${pid}/mirror`, { method: "POST" }),
  openBookFolder: (pid: string) =>
    request<{ ok: boolean; dir: string }>(`/api/books/${pid}/open-folder`, { method: "POST" }),
  textImportReject: (jid: string) =>
    request<{ ok: boolean }>(`/api/chaishu/text-imports/${jid}/reject`, { method: "POST" }),
  // 批次三⑤:压缩本线(纯算法拼前情提要,零 LLM,原文全留库)
  compactSession: (sid: string) =>
    request<{ ok: boolean; compacted: number; digest_chars: number; message: string }>(
      `/api/conversations/${sid}/compact`, { method: "POST", body: JSON.stringify({ keep: 16 }) }),
  putUiSettings: (patch: { auto_compact: boolean; organizer_enabled: boolean }) =>
    request<{ ok: boolean; ui: { auto_compact: boolean; organizer_enabled: boolean } }>(
      "/api/settings/ui", { method: "PUT", body: JSON.stringify(patch) }),
  // 批次六甲:触点覆盖项保存(全量替换;删除=从 map 移除)
  putTouches: (touches: Record<string, { prompt_append?: string; model?: string; max_tokens?: number }>) =>
    request<{ ok: boolean; touches: Record<string, { prompt_append?: string; model?: string; max_tokens?: number }> }>(
      "/api/settings/touches", { method: "PUT", body: JSON.stringify({ touches }) }),
  // ①AI 整理官(设置页总闸默认关;对单节出整理建议,人对比采用)
  textOrganize: (text: string, instruction = "") =>
    request<{ suggestion: string; cost: number; model: string }>("/api/chaishu/text-organize", {
      method: "POST", body: JSON.stringify({ text, instruction }),
    }),
  outlineCreate: (
    pid: string,
    body: { kind: string; parent_id: string | null; title: string }
  ) => request<{ id: string }>(`/api/books/${pid}/outline`, {
    method: "POST",
    body: JSON.stringify(body),
  }),
  outlineMove: (nid: string, direction: "up" | "down") =>
    request(`/api/outline/${nid}/move`, { method: "POST", body: JSON.stringify({ direction }) }),
  outlineDelete: (nid: string) => request(`/api/outline/${nid}`, { method: "DELETE" }),
  outlineStatus: (nid: string, to_status: string) =>
    request(`/api/outline/${nid}/status`, { method: "POST", body: JSON.stringify({ to_status }) }),
  outlineStatusLog: (nid: string) =>
    request<{ log: import("./types").StatusLogRow[] }>(`/api/outline/${nid}/status-log`),
  workbenchPreview: (nid: string, pid: string) =>
    request<import("./types").WorkbenchPreview>(
      `/api/workbench/${nid}/preview?project_id=${pid}`
    ),
  generateDraft: (nid: string, pid: string, skill?: string | null, refPromptIds?: string[]) =>
    request<{ ok: boolean; task: import("./types").GenTask }>(
      `/api/workbench/${nid}/draft?project_id=${pid}`,
      { method: "POST", body: JSON.stringify({ skill: skill ?? null, ref_prompt_ids: refPromptIds ?? null }) }
    ),
  repairAsync: (nid: string, pid: string, skill?: string | null, refPromptIds?: string[]) =>
    request<{ ok: boolean; task: import("./types").GenTask }>(
      `/api/workbench/${nid}/repair?project_id=${pid}`,
      { method: "POST", body: JSON.stringify({ skill: skill ?? null, ref_prompt_ids: refPromptIds ?? null }) }
    ),
  workbenchTask: (tid: string) =>
    request<{ task: import("./types").GenTask }>(`/api/workbench/tasks/${tid}`),
  activeGenTasks: () =>
    request<{ tasks: import("./types").GenTask[] }>("/api/workbench/tasks/active"),
  saveHumanEdit: (nid: string, pid: string, text: string) =>
    request<import("./types").ChangesetView>(`/api/workbench/${nid}/draft?project_id=${pid}`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),
  dismissValidation: (nid: string, pid: string, index: number, note: string) =>
    request<{ ok: boolean; validations: import("./types").Validation[] }>(
      `/api/workbench/${nid}/validations/dismiss?project_id=${pid}`,
      { method: "POST", body: JSON.stringify({ index, note }) }
    ),
  applyChangeset: (nid: string, pid: string) =>
    request<{ ok: boolean; revision: number; md_path: string | null }>(
      `/api/workbench/${nid}/apply?project_id=${pid}`,
      { method: "POST" }
    ),
  setPresence: (eid: string, presence: "always" | "on_demand") =>
    request(`/api/l1/${eid}/presence`, { method: "PUT", body: JSON.stringify({ presence }) }),
  reviewSkills: () =>
    request<{ skills: { key: string; name: string; description: string }[] }>(
      "/api/review/skills"
    ),
  reviewQueue: (pid: string) =>
    request<{ queue: { id: string; title: string; status: string; status_changed_at: string }[] }>(
      `/api/review/queue?project_id=${pid}`
    ),
  approveFinal: (nid: string, pid: string) =>
    request<{ ok: boolean; applied: { revision: number; md_path: string | null }; l2_rewrite: { count?: number; error?: string } | null }>(
      `/api/review/${nid}/approve?project_id=${pid}`, { method: "POST" }
    ),
  rejectFinal: (nid: string, pid: string, note: string) =>
    request(`/api/review/${nid}/reject?project_id=${pid}`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  zhuqueLog: (body: {
    project_id: string;
    node_id: string | null;
    verdict: string;
    human_ratio: number | null;
    suspect_ratio: number | null;
    red_count: number | null;
    note: string;
    red_segments: string[];
    yellow_segments: string[];
    green_segments: string[];
  }) => request("/api/review/zhuque", { method: "POST", body: JSON.stringify(body) }),
  zhuqueRows: (pid: string) =>
    request<{ rows: Record<string, unknown>[]; weekly_reminder: boolean }>(
      `/api/review/zhuque?project_id=${pid}`
    ),
  l2Drafts: (pid: string) =>
    request<{ drafts: { id: string; file_type: string; content: string; before: string; updated_at: string }[] }>(
      `/api/l2/drafts?project_id=${pid}`
    ),
  l2Approve: (draftId: string) =>
    request(`/api/l2/drafts/${draftId}/approve`, { method: "POST" }),
  l2Reject: (draftId: string) =>
    request(`/api/l2/drafts/${draftId}/reject`, { method: "POST" }),
  draftL2Async: (pid: string, nid: string, text: string) =>
    request<{ task: import("./types").GenTask }>(`/api/l2/draft-async?project_id=${pid}`, {
      method: "POST", body: JSON.stringify({ node_id: nid, text }),
    }),
  chaishuImportPreview: (sourcePath: string) =>
    request<{ count: number; per_category: Record<string, number>;
      names: { category: string; name: string }[] }>("/api/chaishu/import-preview", {
      method: "POST", body: JSON.stringify({ source_path: sourcePath }),
    }),
  hookBoard: (pid: string) =>
    request<{ hooks: { detail: string; planted_chapter: number; status: string; age: number; stale: boolean }[]; current_chapter: number; stale_threshold: number }>(
      `/api/l2/hooks?project_id=${pid}`
    ),
  settings: () => request<import("./types").Settings>("/api/settings"),
  putLlm: (patch: Partial<import("./types").LlmSettings>) =>
    request<{ ok: boolean; llm: import("./types").LlmSettings }>("/api/settings/llm", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  putPricing: (patch: {
    default?: import("./types").PriceEntry;
    models?: import("./types").PriceEntry[];
    standard?: import("./types").PriceEntry | null;
    discount_until?: string;
  }) => request("/api/settings/pricing", { method: "PUT", body: JSON.stringify(patch) }),
  putApiKey: (apiKey: string) =>
    request("/api/settings/api-key", { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }),
  putAssembly: (patch: { token_limit?: number | null; body_inject?: boolean }) =>
    request("/api/settings/assembly", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  // 选择填空式预设模板(2026-09-09):全量替换语义(镜像 putTouches)
  putPromptTemplates: (items: import("./types").PromptTemplate[]) =>
    request<{ ok: boolean; prompt_templates: { items: import("./types").PromptTemplate[] } }>(
      "/api/settings/prompt-templates", {
        method: "PUT",
        body: JSON.stringify({ items }),
      }),
  // 输出上下限三层(2026-09-09):全量替换语义
  putOutputLimits: (body: {
    default?: { min_tokens?: number | null; max_tokens?: number | null };
    books?: Record<string, {
      default?: { min_tokens?: number | null; max_tokens?: number | null };
      actions?: Record<string, { min_tokens?: number | null; max_tokens?: number | null }>;
    }>;
  }) =>
    request<{ ok: boolean; output_limits: import("./types").OutputLimits }>(
      "/api/settings/output-limits", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  // 参考提示词库+三层绑定:全量替换语义
  putReferencePrompts: (body: {
    items: import("./types").RefPromptItem[];
    global_bind?: string[];
    actions?: Record<string, string[]>;
    books?: Record<string, string[]>;
  }) =>
    request<{ ok: boolean; reference_prompts: import("./types").ReferencePrompts }>(
      "/api/settings/reference-prompts", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  // 一键备份(候选清单落地批 B)
  backupNow: () =>
    request<{ ok: boolean; file: string }>("/api/settings/backup-now", { method: "POST" }),
  pushBackup: () =>
    request<{ ok: boolean; code: number; output: string }>(
      "/api/settings/push-backup", { method: "POST" }),
  putThinking: (patch: Partial<import("./types").ThinkingSettings>) =>
    request<{ ok: boolean; thinking: import("./types").ThinkingSettings }>(
      "/api/settings/thinking",
      { method: "PUT", body: JSON.stringify(patch) }
    ),
  putSkills: (globalDefault: string) =>
    request<{ ok: boolean; skills: import("./types").SkillsSettings }>("/api/settings/skills", {
      method: "PUT",
      body: JSON.stringify({ global_default: globalDefault }),
    }),
  putMcpServers: (servers: import("./types").McpServer[]) =>
    request<{ ok: boolean; mcp: import("./types").McpSettings }>("/api/settings/mcp", {
      method: "PUT",
      body: JSON.stringify({ servers }),
    }),
  importMcp: (jsonText: string) =>
    request<{ ok: boolean; imported: number; mcp: import("./types").McpSettings; warnings?: string[]; note?: string }>(
      "/api/settings/mcp/import",
      { method: "POST", body: JSON.stringify({ json_text: jsonText }) }
    ),
  setBookSkill: (pid: string, override: string | null) =>
    request<{ ok: boolean; book: import("./types").Book }>(`/api/books/${pid}`, {
      method: "PUT",
      body: JSON.stringify({ skill_override: override }),
    }),
  usageLogs: (limit = 50) =>
    request<{ logs: import("./types").UsageRow[] }>(`/api/usage/logs?limit=${limit}`),

  // ── 统一对话组件(A1/A2/A3,执行书 2026-08-31)──
  conversations: (q: { project_id?: string; owner_type?: string; owner_id?: string }) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v) sp.set(k, v);
    return request<{ sessions: import("./types").ConversationSession[] }>(
      `/api/conversations?${sp.toString()}`);
  },
  createConversation: (body: {
    project_id: string | null; owner_type: string; owner_id: string; name: string;
  }) =>
    request<{ session: import("./types").ConversationSession }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  conversationMessages: (sid: string) =>
    request<{ messages: import("./types").ChatMessage[] }>(`/api/conversations/${sid}/messages`),
  sendConversationMessage: (
    sid: string,
    body: {
      message: string;
      skill?: string | null;
      temperature?: number | null;
      thinking?: string | null;
      attachments?: import("./types").AttachmentRef[];
      preset?: string | null;
      preset_text?: string | null;
      ref_prompt_ids?: string[] | null;
    },
  ) =>
    request<{ ok: boolean; task: import("./types").GenTask }>(
      `/api/conversations/${sid}/messages`, { method: "POST", body: JSON.stringify(body) }),
  adoptSuggestion: (body: { session_id: string; message_id: string; index: number;
    anchor?: { x: number; y: number } | null; tree?: import("./types").SubtopicItem[] }) =>
    request<{
      ok: boolean;
      target: string;
      summary: string;
      node_id?: string;
      field?: string;
      before?: string;
      after?: string;
      changeset?: import("./types").ChangesetView;
    }>("/api/conversations/suggestions/adopt", { method: "POST", body: JSON.stringify(body) }),
  chatRefs: (pid: string) =>
    request<import("./types").ChatRefs>(`/api/conversations/refs?project_id=${pid}`),

  // ── 版本历史(C5)──
  patchHistory: (nid: string, pid: string) =>
    request<{ changeset_id: string; patches: import("./types").PatchRow[] }>(
      `/api/workbench/${nid}/patch-history?project_id=${pid}`),
  rollbackPatch: (nid: string, pid: string, patchId: string) =>
    request<import("./types").ChangesetView>(`/api/workbench/${nid}/patch-rollback?project_id=${pid}`, {
      method: "POST",
      body: JSON.stringify({ patch_id: patchId }),
    }),

  // ── 大纲精修第二批(C1/C2/C3/C4)──
  outlineDetail: (nid: string) =>
    request<import("./types").NodeDetail>(`/api/outline/${nid}/detail`),
  outlineUpdate: (nid: string, patch: { title?: string; summary?: string; note?: string; body?: string }) =>
    request<{ ok: boolean }>(`/api/outline/${nid}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  // WPS 大纲(任务词 2026-09-09):AI 点子两入口(只出建议,不落库)+闸门批准落库
  outlineSubtopicSplit: (nid: string, hint = "", refPromptIds?: string[]) =>
    request<{ tree: import("./types").SubtopicItem[]; cost: number; run_id: string }>(
      `/api/outline/${nid}/ai/subtopic-split`, {
        method: "POST",
        body: JSON.stringify({ hint, ref_prompt_ids: refPromptIds ?? null }),
      }),
  outlineBodySuggest: (nid: string, hint = "", refPromptIds?: string[]) =>
    request<{ text: string; cost: number; run_id: string }>(
      `/api/outline/${nid}/ai/body-suggest`, {
        method: "POST",
        body: JSON.stringify({ hint, ref_prompt_ids: refPromptIds ?? null }),
      }),
  outlineSubtopicAdopt: (nid: string, tree: import("./types").SubtopicItem[]) =>
    request<{ ok: boolean; created: number; summary: string }>(
      `/api/outline/${nid}/subtopics/adopt`, {
        method: "POST",
        body: JSON.stringify({ tree }),
      }),
  putSceneFields: (nid: string, fields: import("./types").SceneFields) =>
    request<{ ok: boolean }>(`/api/outline/${nid}/scene-fields`, {
      method: "PUT",
      body: JSON.stringify(fields),
    }),
  putOutlineSettings: (patch: { scenes_enabled: boolean }) =>
    request<{ ok: boolean; outline: { scenes_enabled: boolean } }>("/api/settings/outline", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  createBranch: (nodeId: string, name: string) =>
    request<{ branch: import("./types").BranchSession }>("/api/conversations/branches", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, name }),
    }),
  listBranches: (nodeId: string) =>
    request<{ branches: import("./types").BranchSession[] }>(
      `/api/conversations/branches?node_id=${nodeId}`),
  putBranchPayload: (sid: string, payload: import("./types").BranchSession["branch_payload"]) =>
    request<{ ok: boolean; branch: import("./types").BranchSession }>(
      `/api/conversations/branches/${sid}/payload`, {
        method: "PUT",
        body: JSON.stringify({ payload }),
      }),
  promoteBranch: (sid: string) =>
    request<{ ok: boolean; applied: { field: string; before: string; after: string }[] }>(
      `/api/conversations/branches/${sid}/promote`, { method: "POST" }),
  archiveBranch: (sid: string) =>
    request<{ ok: boolean; status: string }>(`/api/conversations/branches/${sid}/archive`, {
      method: "POST",
    }),

  // ── 第三批(任务词 2026-09-01)──
  dashboard: (pid: string) =>
    request<import("./types").DashboardData>(`/api/books/${pid}/dashboard`),
  putDashboardWeights: (pid: string, w: { w_review?: number; w_zhuque?: number; w_cost?: number }) =>
    request<{ ok: boolean }>(`/api/books/${pid}/dashboard/weights`, {
      method: "PUT",
      body: JSON.stringify(w),
    }),
  productionTimeline: (nid: string, pid: string) =>
    request<{ node: { title: string; status: string; status_label: string }; events: import("./types").ProductionEvent[] }>(
      `/api/workbench/${nid}/production-timeline?project_id=${pid}`),
  wordStats: (pid: string, nodeId?: string, since?: string) => {
    const sp = new URLSearchParams();
    if (nodeId) sp.set("node_id", nodeId);
    if (since) sp.set("since", since);
    const qs = sp.toString();
    const base = pid ? `/api/books/${pid}/word-stats` : "/api/word-stats";
    return request<import("./types").WordStats>(base + (qs ? `?${qs}` : ""));
  },
  // 二期③:章节信息卡(四行直写既有表;消费者 a 装配注入/b 体检新规)
  cardGet: (nid: string, pid: string) =>
    request<import("./types").ChapterCard>(`/api/card/${nid}?pid=${encodeURIComponent(pid)}`),
  cardSave: (nid: string, pid: string, body: {
    summary?: string; note?: string; event_ids?: string[]; cast_node_ids?: string[];
  }) =>
    request<{ ok: boolean }>(`/api/card/${nid}?pid=${encodeURIComponent(pid)}`,
      { method: "PUT", body: JSON.stringify(body) }),
  // 章节卡 AI 预填(候选清单落地批 A):只出建议,diff 确认后前端调 cardSave
  cardAiFill: (nid: string, pid: string, hint = "", refPromptIds?: string[]) =>
    request<{ summary: string; note: string; event_titles: string[];
      character_labels: string[]; cost: number }>(
      `/api/card/${nid}/ai-fill?pid=${encodeURIComponent(pid)}`,
      { method: "POST",
        body: JSON.stringify({ hint, ref_prompt_ids: refPromptIds ?? null }) }),
  // 阅读模式数据源(候选清单落地批 B)
  reading: (pid: string, mode: "all" | "finalized" = "all") =>
    request<{ book_name: string; chapters: { id: string; title: string;
      status: string; content: string }[] }>(
      `/api/books/${pid}/reading?mode=${mode}`),
  // 人物戏份曲线(候选清单落地批 A)
  screenTime: (pid: string) =>
    request<{ roles: { name: string; chapter_nos: number[]; count: number }[] }>(
      `/api/books/${pid}/screen-time`),
  timelineEvents: (pid: string) =>
    request<{ events: import("./types").TimelineEvent[] }>(`/api/books/${pid}/timeline-events`),
  createTimelineEvent: (pid: string, body: {
    time_label: string; title: string; summary: string; line: string; status: string;
  }) =>
    request<{ event: import("./types").TimelineEvent }>(`/api/books/${pid}/timeline-events`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateTimelineEvent: (eid: string, patch: Partial<{
    time_label: string; title: string; summary: string; line: string; status: string;
  }>) =>
    request<{ ok: boolean }>(`/api/timeline/${eid}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  deleteTimelineEvent: (eid: string) =>
    request<{ ok: boolean }>(`/api/timeline/${eid}`, { method: "DELETE" }),
  timelineEventDetail: (eid: string) =>
    request<{ event: import("./types").TimelineEvent }>(`/api/timeline/${eid}/detail`),
  linkEventChapter: (eid: string, nodeId: string) =>
    request(`/api/timeline/${eid}/chapters`, {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId }),
    }),
  unlinkEventChapter: (eid: string, nodeId: string) =>
    request<{ ok: boolean }>(`/api/timeline/${eid}/chapters/${nodeId}`, { method: "DELETE" }),

  // ── 第四批:统一图谱引擎 ──
  graphBoards: (pid: string) =>
    request<{ boards: import("./types").GraphBoard[]; kinds: string[] }>(
      `/api/graphs/books/${pid}/boards`),
  createGraphBoard: (pid: string, body: { kind: string; name: string }) =>
    request<{ board: import("./types").GraphBoard }>(`/api/graphs/boards/${pid}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteGraphBoard: (bid: string) =>
    request<{ ok: boolean }>(`/api/graphs/boards/${bid}`, { method: "DELETE" }),
  patchGraphBoard: (bid: string, patch: { grid_on?: number; name?: string }) =>
    request<{ board: import("./types").GraphBoard }>(`/api/graphs/boards/${bid}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  graphBoard: (bid: string) =>
    request<{
      board: import("./types").GraphBoard;
      nodes: import("./types").GraphNode[];
      edges: import("./types").GraphEdge[];
    }>(`/api/graphs/boards/${bid}`),
  createGraphNode: (bid: string, body: {
    label: string; sub_label?: string | null; ref_type?: string;
    ref_id?: string | null; x?: number; y?: number;
  }) =>
    request<{ node: import("./types").GraphNode }>(`/api/graphs/boards/${bid}/nodes`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchGraphNode: (nid: string, patch: {
    x?: number; y?: number; label?: string; sub_label?: string | null;
    style?: Record<string, unknown>;
  }) =>
    request<{ node: import("./types").GraphNode }>(`/api/graphs/nodes/${nid}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteGraphNode: (nid: string) =>
    request<{ ok: boolean }>(`/api/graphs/nodes/${nid}`, { method: "DELETE" }),
  createGraphEdge: (bid: string, body: {
    from_node_id: string; to_node_id: string; label?: string; kind?: string;
  }) =>
    request<{ edge: import("./types").GraphEdge }>(`/api/graphs/boards/${bid}/edges`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchGraphEdge: (eid: string, patch: { label?: string; kind?: string;
    style?: Record<string, unknown> }) =>
    request<{ edge: import("./types").GraphEdge }>(`/api/graphs/edges/${eid}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteGraphEdge: (eid: string) =>
    request<{ ok: boolean }>(`/api/graphs/edges/${eid}`, { method: "DELETE" }),
  generateGraphNodes: (bid: string, body: { source: string; category?: string }) =>
    request<{ ok: boolean; created: number; skipped: number }>(
      `/api/graphs/boards/${bid}/generate`, { method: "POST", body: JSON.stringify(body) }),
  // B3 实体互链(骨架批执行书 §3):聚合某实体的关联对象
  entityLinks: (pid: string, etype: string, id: string) =>
    request<import("./types").EntityLinks>(
      `/api/books/${pid}/entity-links?etype=${encodeURIComponent(etype)}&id=${encodeURIComponent(id)}`),
  // 批次七②:分层搜索(FTS5 trigram 分组返回;pid 缺省=跨全书)
  search: (q: string, pid?: string) =>
    request<import("./types").SearchResponse>(
      `/api/search?q=${encodeURIComponent(q)}${pid ? `&pid=${encodeURIComponent(pid)}` : ""}`),
  // 批次七⑥:模板双层(存→选→套;预设题材包与用户模板分组)
  templatesList: () =>
    request<import("./types").TemplatesList>("/api/templates"),
  saveTemplate: (name: string, boardId: string) =>
    request<{ ok: boolean; id: string; node_count: number; edge_count: number }>(
      "/api/templates", { method: "POST", body: JSON.stringify({ name, board_id: boardId }) }),
  deleteTemplate: (tid: string) =>
    request<{ ok: boolean }>(`/api/templates/${tid}`, { method: "DELETE" }),
  applyTemplate: (tid: string, pid: string, name?: string) =>
    request<{ ok: boolean; board: import("./types").GraphBoard }>(
      `/api/templates/${tid}/apply`,
      { method: "POST", body: JSON.stringify({ pid, name: name ?? "" }) }),
  applyPack: (key: string, pid: string) =>
    request<{ ok: boolean; boards: import("./types").GraphBoard[] }>(
      `/api/templates/packs/${key}/apply`,
      { method: "POST", body: JSON.stringify({ pid }) }),
  applyPackBoard: (key: string, idx: number, pid: string, name?: string) =>
    request<{ ok: boolean; board: import("./types").GraphBoard }>(
      `/api/templates/packs/${key}/boards/${idx}/apply`,
      { method: "POST", body: JSON.stringify({ pid, name: name ?? "" }) }),
  // 批次七⑤:构思树(下钻子讨论;三态=待议/采纳/放弃)
  ideasList: (pid: string) =>
    request<{ ideas: import("./types").IdeaNode[] }>(
      `/api/ideas?pid=${encodeURIComponent(pid)}`),
  ideasCreate: (body: {
    pid: string; title: string; note?: string;
    parent_idea_id?: string | null;
    source_ref?: { session_id?: string; message_id?: string; idx?: number } | null;
  }) =>
    request<{ idea: import("./types").IdeaNode }>("/api/ideas",
      { method: "POST", body: JSON.stringify(body) }),
  ideasPatch: (iid: string, patch: { title?: string; note?: string; status?: string }) =>
    request<{ idea: import("./types").IdeaNode }>(`/api/ideas/${iid}`,
      { method: "PATCH", body: JSON.stringify(patch) }),
  ideasDelete: (iid: string) =>
    request<{ ok: boolean; deleted: number }>(`/api/ideas/${iid}`, { method: "DELETE" }),
};
