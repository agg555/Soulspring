import { useEffect, useState, type ChangeEvent } from "react";
import { api } from "../api";
import type {
  BranchSession, NodeDetail, RefPromptItem, SceneFields, SubtopicItem, Suggestion,
} from "../types";
import ChatPanel from "./ChatPanel";
import SubtopicTreeEditor from "./SubtopicTreeEditor";
import RefPromptPicker from "./RefPromptPicker";
import { uiConfirm } from "./uiConfirm";

/**
 * 节点详情抽屉(第二批 C2/C3/C4,执行书 2026-08-31;WPS 大纲 2026-09-09 扩):
 * - 点任意大纲节点 → 右抽屉:标题/摘要/备注人可编辑落库 + 状态机+时间戳(章)+
 *   子节点 + 场景五字段(scene)+ 字段历史;(章级)入口到工作台/终审台;
 * - WPS 节点正文(body):卷/总纲/近纲/子题可带正文段(写作样式;章正文仍走 l4);
 * - WPS AI 点子:AI 拆子题 / AI 正文建议——只出建议,闸门窗人确认后才落库
 *   (subtopics/adopt 人批准端点 / PUT outline 轻档写回),AI 永不直写;
 * - C3 节点级 AI 对话:内嵌 ChatPanel(ownerType=outline_node),预设「优化/奇思妙想」;
 * - C4 分支探索(章/场景):分支 = 特殊会话 + 字段草稿包;草稿可编辑 + 分支内对话;
 *   三种结局:[转正](diff 确认写回主干,原值进版本历史)/[归档]/[继续聊]。
 */
const KIND_LABEL: Record<string, string> = {
  category: "总纲", volume: "卷", arc: "近纲", chapter: "章", scene: "场景", topic: "子题",
};
// body 编辑区开放给"非章但要有文字"的节点(任务词 W2:章正文仍是 l4 管道)
const HAS_BODY_KINDS = new Set(["category", "volume", "arc", "topic"]);
const BODY_MAX = 20000;   // 与后端 outline.TOPIC_BODY_MAX 同口径
const SCENE_FIELD_LABEL: Record<keyof SceneFields, string> = {
  goal: "场景目标", conflict: "冲突", hook: "出口钩子",
  characters: "出场角色", target_words: "预计字数",
};
const STATUS_LABEL: Record<string, string> = {
  unwritten: "未写", draft: "草稿", human_editing: "人改中",
  final_review: "待终审", finalized: "定稿",
};

export default function NodeDrawer({ pid, nid, onClose, onChanged, onGoPanel, onSwitch, onShowLinks }: {
  pid: string;
  nid: string;
  onClose: () => void;
  onChanged: () => void;                                    // 主干变化后通知树刷新
  onGoPanel?: (tab: "workbench" | "review") => void;
  onSwitch?: (nid: string) => void;                         // A2:抽屉内点子节点切换对象
  onShowLinks?: (etype: string, nid: string, title: string) => void;  // B3 互链抽屉(执行书 §3)
}) {
  const [detail, setDetail] = useState<NodeDetail["node"] | null>(null);
  const [branches, setBranches] = useState<BranchSession[]>([]);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [note, setNote] = useState("");
  const [body, setBody] = useState("");
  // WPS AI 点子闸门:拆子题树(人改后批准落库)/ 正文建议(人 diff 确认后轻档写回)
  const [splitGate, setSplitGate] = useState<SubtopicItem[] | null>(null);
  const [bodySuggest, setBodySuggest] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState("");
  // 参考提示词(2026-09-09):多选手选随 AI 调用注入(仅作参考)
  const [refItems, setRefItems] = useState<RefPromptItem[]>([]);
  const [refIds, setRefIds] = useState<string[]>([]);
  useEffect(() => {
    api.settings().then((st) => setRefItems(st.reference_prompts?.items ?? [])).catch(() => {});
  }, []);
  const [scene, setScene] = useState<SceneFields>(
    { goal: "", conflict: "", hook: "", characters: "", target_words: "" });
  const [openBranch, setOpenBranch] = useState<BranchSession | null>(null);
  const [branchDraft, setBranchDraft] = useState<BranchSession["branch_payload"]>({});
  const [newBranchName, setNewBranchName] = useState("");
  const [promoteDiff, setPromoteDiff] = useState<BranchSession | null>(null);
  const [promoteRows, setPromoteRows] = useState<{ field: string; before: string; after: string }[]>([]);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 4000); };

  // 顺手修:轻档采纳改前值(outline_field 仅 title/summary/note)——不传则采纳弹窗"改前"恒为空
  const getAdoptBefore = (s: Suggestion): string => {
    const t = (s.target ?? {}) as Record<string, unknown>;
    const map: Record<string, string> = { title, summary, note };
    return t.field ? map[String(t.field)] ?? "" : "";
  };

  const load = () => {
    api.outlineDetail(nid).then((r) => {
      const n = r.node;
      setDetail(n);
      setTitle(n.title);
      setSummary(n.summary ?? "");
      setNote(n.note ?? "");
      setBody(n.body ?? "");
      setScene({
        goal: n.scene_fields?.goal ?? "", conflict: n.scene_fields?.conflict ?? "",
        hook: n.scene_fields?.hook ?? "", characters: n.scene_fields?.characters ?? "",
        target_words: n.scene_fields?.target_words ?? "",
      });
    }).catch((e) => setError(String(e.message || e)));
    api.listBranches(nid).then((r) => setBranches(r.branches)).catch(() => {});
  };
  useEffect(load, [nid]);

  const saveBase = async () => {
    if (!detail) return;
    setBusy("保存中…");
    setError("");
    try {
      await api.outlineUpdate(nid, {
        title: title.trim() || detail.title,
        summary, note,
        ...(HAS_BODY_KINDS.has(detail.kind) ? { body } : {}),
      });
      flash("节点字段已保存");
      load();
      onChanged();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  // ── WPS AI 点子(闸门:AI 只出建议,人批准才落库)──
  const runSplit = async () => {
    setAiBusy("split");
    setError("");
    try {
      const r = await api.outlineSubtopicSplit(nid, "", refIds.length ? refIds : undefined);
      setSplitGate(r.tree);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setAiBusy("");
    }
  };
  const approveSplit = async () => {
    if (!splitGate) return;
    setBusy("落库中…");
    setError("");
    try {
      const r = await api.outlineSubtopicAdopt(nid, splitGate);
      setSplitGate(null);
      flash(r.summary || `已创建 ${r.created} 个子题`);
      load();
      onChanged();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };
  const runBodySuggest = async () => {
    setAiBusy("body");
    setError("");
    try {
      const r = await api.outlineBodySuggest(nid, "", refIds.length ? refIds : undefined);
      setBodySuggest(r.text);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setAiBusy("");
    }
  };
  const approveBodySuggest = async () => {
    if (bodySuggest == null) return;
    setBusy("写回中…");
    setError("");
    try {
      await api.outlineUpdate(nid, { body: bodySuggest });
      setBodySuggest(null);
      flash("正文建议已采纳写回");
      load();
      onChanged();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  const saveScene = async () => {
    setBusy("保存场景…");
    setError("");
    try {
      await api.putSceneFields(nid, scene);
      flash("场景五字段已保存");
      load();
      onChanged();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  const changeStatus = async (to: string, e?: ChangeEvent<HTMLSelectElement>) => {
    // 二期②:定稿解封二次确认(取消则把下拉拨回原值)
    if (detail?.status === "finalized" && to !== "finalized") {
      const ok = await uiConfirm(`「${detail.title}」已定稿,解封回「${to}」?`);
      if (!ok) {
        if (e) e.currentTarget.value = detail.status;
        return;
      }
    }
    setError("");
    try {
      await api.outlineStatus(nid, to);
      load();
      onChanged();
    } catch (e2: unknown) {
      setError(String((e2 as Error).message || e2));
    }
  };

  // ── 分支探索(C4)──
  const createBranch = async () => {
    if (!newBranchName.trim()) return;
    setError("");
    try {
      const r = await api.createBranch(nid, newBranchName.trim());
      setNewBranchName("");
      setBranches((cur) => [...cur, r.branch]);
      openBranchView(r.branch);
      flash("分支已开:里面改的都是草稿,主干纹丝不动");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const openBranchView = (b: BranchSession) => {
    setPromoteDiff(null);
    setOpenBranch(b);
    setBranchDraft({ ...b.branch_payload });
  };

  const saveBranchDraft = async () => {
    if (!openBranch) return;
    setError("");
    try {
      const r = await api.putBranchPayload(openBranch.id, branchDraft);
      setOpenBranch(r.branch);
      setBranchDraft({ ...r.branch.branch_payload });
      flash("草稿已保存(主干未动)");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  // 转正 diff:草稿 vs 主干当前值,仅列有变化的字段
  const beginPromote = () => {
    if (!detail || !openBranch) return;
    const cur = {
      title: detail.title, summary: detail.summary ?? "", note: detail.note ?? "",
      scene_fields: detail.scene_fields ?? {},
    };
    const rows: { field: string; before: string; after: string }[] = [];
    for (const f of ["title", "summary", "note"] as const) {
      const after = String(openBranch.branch_payload[f] ?? "");
      if (after && after !== cur[f]) rows.push({ field: f, before: cur[f], after });
    }
    if (detail.kind === "scene" && openBranch.branch_payload.scene_fields) {
      const before = JSON.stringify(cur.scene_fields);
      const after = JSON.stringify(openBranch.branch_payload.scene_fields);
      if (after !== before) {
        rows.push({ field: "scene_fields", before, after });
      }
    }
    if (rows.length === 0) {
      flash("草稿与主干一致,没有可转正的字段");
      return;
    }
    setPromoteRows(rows);
    setPromoteDiff(openBranch);
  };

  const confirmPromote = async () => {
    if (!openBranch) return;
    setBusy("转正中…");
    setError("");
    try {
      const r = await api.promoteBranch(openBranch.id);
      setPromoteDiff(null);
      setPromoteRows([]);
      setOpenBranch(null);
      flash(`已转正 ${r.applied.length} 个字段;原值已进版本历史`);
      load();
      onChanged();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  const archiveBranch = async (b: BranchSession) => {
    setError("");
    try {
      await api.archiveBranch(b.id);
      if (openBranch?.id === b.id) { setOpenBranch(null); setPromoteDiff(null); setPromoteRows([]); }
      load();
      flash("分支已归档(草稿保留可回看)");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  return (
    <>
      {/* 体感三桶第三轮:点抽屉外即关闭(背板),防点击/拖拽穿透到底层树/画布 */}
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="node-drawer">
      <div className="row spread">
        <span className={`kind kind-${detail?.kind ?? ""}`}>
          {KIND_LABEL[detail?.kind ?? ""] ?? "…"}
        </span>
        <span className="row" style={{ margin: 0 }}>
          {onShowLinks && detail && (
            <button className="link" onClick={() => onShowLinks("outline_node", nid, detail.title)}>
              🔗 关联
            </button>
          )}
          <button className="link" onClick={onClose}>关闭抽屉 ×</button>
        </span>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}
      {busy && <p className="muted">{busy}</p>}
      {!detail && <p className="muted">加载中…</p>}

      {detail && (
        <>
          <h3 style={{ marginTop: 8 }}>{detail.title}</h3>
          {detail.kind === "chapter" && (
            <div className="row">
              <span className={`badge ${detail.status === "finalized" ? "ok" : ""}`}>
                {detail.status_label ?? detail.status}
              </span>
              <select value={detail.status} onChange={(e) => changeStatus(e.target.value, e)}>
                <option value={detail.status}>{detail.status_label ?? detail.status}</option>
                {detail.allowed_transitions?.map((s) => (
                  <option key={s} value={s}>{STATUS_LABEL[s] ?? s}</option>
                ))}
              </select>
              <button className="link" onClick={() => onGoPanel?.("workbench")}>去工作台 →</button>
              <button className="link" onClick={() => onGoPanel?.("review")}>去终审台 →</button>
            </div>
          )}
          {detail.status_log.length > 0 && (
            <p className="muted small">
              状态时间戳:{detail.status_log.map((l) =>
                `${l.changed_at.replace("T", " ").slice(0, 16)} ${l.from_status ?? "—"}→${l.to_status}`).join(";")}
            </p>
          )}

          <div className="form">
            <label>标题
              <input value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className="full">摘要(人可编辑)
              <textarea rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} />
            </label>
            <label className="full">备注(人可编辑)
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
          </div>
          <div className="row">
            <button className="primary" onClick={saveBase} disabled={!!busy}>保存节点字段</button>
          </div>

          {detail && HAS_BODY_KINDS.has(detail.kind) && (
            <>
              <h3>正文(WPS 式节点内容段)</h3>
              <textarea
                className="node-body-editor"
                rows={8}
                placeholder="标题下的正文文字(设定说明/纲要/细节),随存随显;悬浮树中标题可预览前 100 字。"
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
              <p className="muted small">
                {body.length}/{BODY_MAX} 字;章的正文不走这里(在工作台 l4 管道)。
              </p>
              <div className="row">
                <RefPromptPicker items={refItems} selected={refIds} onChange={setRefIds} />
                <button className="link" disabled={!!aiBusy || !!busy}
                  title="AI 读本节点上下文,提议拆成子题树;弹出闸门窗,人可增删改再批准落库"
                  onClick={runSplit}>{aiBusy === "split" ? "⏳ AI 拆子题中" : "🤖 AI 拆子题"}</button>
                <button className="link" disabled={!!aiBusy || !!busy}
                  title="AI 对本节点正文出改写建议稿;diff 确认后才写回(轻档)"
                  onClick={runBodySuggest}>{aiBusy === "body" ? "⏳ AI 正文建议中" : "✍️ AI 正文建议"}</button>
                {aiBusy && (
                  <span className="muted small">
                    {aiBusy === "split"
                      ? "AI 拆子题中…(只出建议,弹出后可增删改再批准)"
                      : "AI 正文建议中…(产出建议稿,diff 确认后才写回)"}
                  </span>
                )}
              </div>
            </>
          )}

          {/* 子题拆分闸门窗:AI 的树先经人增删改,批准才落库(AI 永不直写) */}
          {splitGate && (
            <div className="dialog">
              <p><b>子题拆分确认(批准闸门)</b>:AI 的建议树已列出,可改标题/删项/加子级;
                批准后按现状落为「子题」节点。</p>
              <SubtopicTreeEditor tree={splitGate} onChange={setSplitGate} />
              <div className="row">
                <button className="primary" onClick={approveSplit} disabled={!!busy}>
                  批准落库
                </button>
                <button onClick={() => setSplitGate(null)}>取消(不落库)</button>
              </div>
            </div>
          )}

          {/* 正文建议轻档闸门:改前/改后 diff → 人确认写回 */}
          {bodySuggest != null && (
            <div className="dialog">
              <p><b>正文建议确认(轻档)</b>:确认后 AI 建议稿写回本节点正文。</p>
              <div className="diff-grid">
                <div>
                  <p className="muted small">当前正文</p>
                  <pre className="diff-pane">{body || "(空)"}</pre>
                </div>
                <div>
                  <p className="muted small">AI 建议稿</p>
                  <pre className="diff-pane">{bodySuggest || "(空)"}</pre>
                </div>
              </div>
              <div className="row">
                <button className="primary" onClick={approveBodySuggest} disabled={!!busy}>
                  采纳写回
                </button>
                <button onClick={() => setBodySuggest(null)}>取消</button>
              </div>
            </div>
          )}

          {detail.kind === "scene" && (
            <>
              <h3>场景五字段</h3>
              <div className="form">
                {(Object.keys(SCENE_FIELD_LABEL) as (keyof SceneFields)[]).map((k) => (
                  <label key={k} className="full">
                    {SCENE_FIELD_LABEL[k]}
                    <input value={scene[k]}
                      onChange={(e) => setScene({ ...scene, [k]: e.target.value })} />
                  </label>
                ))}
              </div>
              <div className="row">
                <button className="primary" onClick={saveScene} disabled={!!busy}>保存五字段</button>
              </div>
            </>
          )}

          <h3>子节点({detail.children.length})</h3>
          {detail.children.length === 0 && <p className="muted small">暂无子节点。</p>}
          <ul className="entry-list">
            {detail.children.map((c) => (
              <li key={c.id} className="entry entry-head">
                <span className={`kind kind-${c.kind}`}>{KIND_LABEL[c.kind] ?? c.kind}</span>
                <button className="link" title="在抽屉中打开该节点"
                  onClick={() => onSwitch?.(c.id)}><b>{c.title}</b></button>
                {c.kind === "chapter" && <span className="badge">{STATUS_LABEL[c.status] ?? c.status}</span>}
              </li>
            ))}
          </ul>

          {detail.field_history.length > 0 && (
            <>
              <h3>字段版本历史(转正/采纳留痕)</h3>
              {detail.field_history.map((h, i) => (
                <p key={i} className="small">
                  {h.created_at.replace("T", " ").slice(0, 16)} · <b>{h.field}</b>:
                  「{(h.before || "(空)").slice(0, 30)}」→「{(h.after || "(空)").slice(0, 30)}」({h.source})
                </p>
              ))}
            </>
          )}

          {(detail.kind === "chapter" || detail.kind === "scene") && (
            <>
              <h3>分支探索</h3>
              <p className="muted small">
                分支里改的都是草稿+对话,主干纹丝不动;结局:[转正] diff 确认写回 /
                [归档] / [继续聊]。
              </p>
              <div className="row">
                <input placeholder="分支名,如:换一个开场" value={newBranchName}
                  onChange={(e) => setNewBranchName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") createBranch(); }} />
                <button onClick={createBranch}>+ 开分支</button>
              </div>
              <ul className="entry-list">
                {branches.map((b) => (
                  <li key={b.id} className={`entry${b.status === "archived" ? " branch-archived" : ""}`}>
                    <div className="entry-head">
                      <b>{b.name}</b>
                      <span className={b.status === "active" ? "badge info" : "badge"}>
                        {b.status === "active" ? "进行中" : "已结案"}
                      </span>
                    </div>
                    <div className="row" style={{ margin: "6px 0 0" }}>
                      <button className="link" onClick={() => openBranchView(b)}>打开</button>
                      {b.status === "active" && (
                        <>
                          <button className="link" onClick={() => { openBranchView(b); beginPromote(); }}>转正</button>
                          <button className="link" onClick={() => archiveBranch(b)}>归档</button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
                {branches.length === 0 && <li className="muted small">还没有分支。</li>}
              </ul>
            </>
          )}

          {/* C3 节点级 AI 对话:上下文 = 祖先链 + 本节点字段 + L1 常驻;优化/奇思妙想预设 */}
          <ChatPanel
            projectId={pid}
            ownerType="outline_node"
            ownerId={nid}
            defaultSessionName={`节点讨论·${detail.title}`}
            allowPresets
            allowSkill
            allowRefs
            getAdoptBefore={getAdoptBefore}
            emptyHint="节点级对话:AI 上下文 = 祖先链 + 本节点字段 + 相关档案。选「优化」要改法,选「奇思妙想」要 3-5 个方向。"
          />
        </>
      )}

      {/* 分支视图:草稿编辑 + 分支内对话(直连该分支会话) */}
      {openBranch && (
        <div className="branch-view">
          <div className="row spread">
            <b>分支:{openBranch.name}</b>
            <button className="link" onClick={() => { setOpenBranch(null); setPromoteDiff(null); }}>退出分支</button>
          </div>
          {openBranch.status !== "active" && (
            <p className="muted small">此分支已结案,草稿只读。</p>
          )}
          <div className="form">
            <label>草稿·标题
              <input value={branchDraft.title ?? ""} disabled={openBranch.status !== "active"}
                onChange={(e) => setBranchDraft({ ...branchDraft, title: e.target.value })} />
            </label>
            <label className="full">草稿·摘要
              <textarea rows={2} value={branchDraft.summary ?? ""} disabled={openBranch.status !== "active"}
                onChange={(e) => setBranchDraft({ ...branchDraft, summary: e.target.value })} />
            </label>
            <label className="full">草稿·备注
              <textarea rows={2} value={branchDraft.note ?? ""} disabled={openBranch.status !== "active"}
                onChange={(e) => setBranchDraft({ ...branchDraft, note: e.target.value })} />
            </label>
            {detail?.kind === "scene" && branchDraft.scene_fields &&
              (Object.keys(SCENE_FIELD_LABEL) as (keyof SceneFields)[]).map((k) => (
                <label key={k} className="full">
                  草稿·{SCENE_FIELD_LABEL[k]}
                  <input value={branchDraft.scene_fields?.[k] ?? ""} disabled={openBranch.status !== "active"}
                    onChange={(e) => setBranchDraft({
                      ...branchDraft,
                      scene_fields: { ...(branchDraft.scene_fields ?? {}), [k]: e.target.value },
                    })} />
                </label>
              ))}
          </div>
          {openBranch.status === "active" && (
            <div className="row">
              <button className="primary" onClick={saveBranchDraft}>保存草稿(不动主干)</button>
              <button onClick={beginPromote}>转正…</button>
              <button onClick={() => archiveBranch(openBranch)}>归档</button>
            </div>
          )}

          {/* 转正 diff 确认(轻档同款交互:改前/改后 → 人确认) */}
          {promoteDiff && promoteRows.length > 0 && (
            <div className="dialog">
              <p><b>转正确认</b>:以下字段将写回主干,原值进版本历史。</p>
              {promoteRows.map((r, i) => (
                <div key={i}>
                  <p className="small"><b>{r.field === "scene_fields" ? "场景五字段" : r.field}</b></p>
                  <div className="diff-grid">
                    <div><p className="muted small">改前(主干)</p><pre className="diff-pane">{r.before || "(空)"}</pre></div>
                    <div><p className="muted small">改后(草稿)</p><pre className="diff-pane">{r.after || "(空)"}</pre></div>
                  </div>
                </div>
              ))}
              <div className="row">
                <button className="primary" onClick={confirmPromote} disabled={!!busy}>确认转正</button>
                <button onClick={() => setPromoteDiff(null)}>取消(继续聊)</button>
              </div>
            </div>
          )}

          <ChatPanel
            projectId={pid}
            ownerType="branch"
            ownerId={nid}
            sessionId={openBranch.id}
            defaultSessionName={openBranch.name}
            allowPresets
            allowSkill
            allowRefs
            emptyHint="在分支里继续聊:AI 的上下文 = 主干现状 + 本分支草稿。"
          />
        </div>
      )}
      </div>
    </>
  );
}
