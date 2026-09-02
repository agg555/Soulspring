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
      detail = body.detail ?? JSON.stringify(body);
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
    body: { category: string; name: string; fields: Record<string, string>; notes: string }
  ) =>
    request(`/api/books/${pid}/l1`, { method: "POST", body: JSON.stringify(body) }),
  l1Update: (
    eid: string,
    patch: { name: string; fields: Record<string, string>; notes: string }
  ) => request<import("./types").L1Entry>(`/api/l1/${eid}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  }),
  l1Approve: (eid: string) => request(`/api/l1/${eid}/approve`, { method: "POST" }),
  l1Delete: (eid: string) => request(`/api/l1/${eid}`, { method: "DELETE" }),
  buildPropose: (pid: string) =>
    request<import("./types").BuildResult>(`/api/books/${pid}/build/propose`, {
      method: "POST",
    }),
  outline: (pid: string) =>
    request<{ nodes: import("./types").OutlineNode[]; status_labels: Record<string, string> }>(
      `/api/books/${pid}/outline`
    ),
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
  generateDraft: (nid: string, pid: string, skill?: string | null) =>
    request<{ ok: boolean; task: import("./types").GenTask }>(
      `/api/workbench/${nid}/draft?project_id=${pid}`,
      { method: "POST", body: JSON.stringify({ skill: skill ?? null }) }
    ),
  repairAsync: (nid: string, pid: string, skill?: string | null) =>
    request<{ ok: boolean; task: import("./types").GenTask }>(
      `/api/workbench/${nid}/repair?project_id=${pid}`,
      { method: "POST", body: JSON.stringify({ skill: skill ?? null }) }
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
  l2Redraft: (pid: string, nid: string, text: string) =>
    request(`/api/l2/draft?project_id=${pid}`, {
      method: "POST",
      body: JSON.stringify({ node_id: nid, text }),
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
  }) => request("/api/settings/pricing", { method: "PUT", body: JSON.stringify(patch) }),
  putApiKey: (apiKey: string) =>
    request("/api/settings/api-key", { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }),
  putAssembly: (tokenLimit: number | null) =>
    request("/api/settings/assembly", {
      method: "PUT",
      body: JSON.stringify({ token_limit: tokenLimit }),
    }),
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
  agentRuns: (limit = 50) =>
    request<{ runs: unknown[] }>(`/api/usage/runs?limit=${limit}`),

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
      attachments?: import("./types").AttachmentRef[];
      preset?: string | null;
    },
  ) =>
    request<{ ok: boolean; task: import("./types").GenTask }>(
      `/api/conversations/${sid}/messages`, { method: "POST", body: JSON.stringify(body) }),
  adoptSuggestion: (body: { session_id: string; message_id: string; index: number }) =>
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
  outlineUpdate: (nid: string, patch: { title?: string; summary?: string; note?: string }) =>
    request<{ ok: boolean }>(`/api/outline/${nid}`, {
      method: "PUT",
      body: JSON.stringify(patch),
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
    request(`/api/timeline/${eid}/chapters/${nodeId}`, { method: "DELETE" }),
  relations: (pid: string) =>
    request<{
      characters: { id: string; name: string; entry_status: string }[];
      relations: import("./types").CharacterRelation[];
      kinds: string[];
    }>(`/api/books/${pid}/relations`),

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
  patchGraphEdge: (eid: string, patch: { label?: string; kind?: string }) =>
    request<{ edge: import("./types").GraphEdge }>(`/api/graphs/edges/${eid}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteGraphEdge: (eid: string) =>
    request<{ ok: boolean }>(`/api/graphs/edges/${eid}`, { method: "DELETE" }),
  generateGraphNodes: (bid: string, body: { source: string; category?: string }) =>
    request<{ ok: boolean; created: number; skipped: number }>(
      `/api/graphs/boards/${bid}/generate`, { method: "POST", body: JSON.stringify(body) }),
};
