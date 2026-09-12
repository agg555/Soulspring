import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { STAGE_LABELS } from "../stages";
import { uiConfirm } from "../components/uiConfirm";
import RefPromptPicker from "../components/RefPromptPicker";
import WordFloat from "../components/WordFloat";
import ChapterCard from "../components/ChapterCard";
import type {
  ChangesetView, GenStage, GenTask, OutlineNode, PatchRow, SkillInfo, WorkbenchPreview,
} from "../types";

/**
 * 写章工作台(M3 核心,7 页之一):
 * 装配预览 → 后台生成草稿(计划卡+草稿+规整+双层审计) → diff 人改 / AI 自修 → 待终审。
 * 左右分栏:左 = 正式正文(基线),右 = 当前草稿(patch.after,可编辑)。
 *
 * 需求1(2026-08-31):生成/自修为后台任务,提交即拿任务号,本页轮询进度;
 * 切到任何页签都不会打断(后端继续跑),回来由 preview.running_task 或顶栏徽标接上;
 * 同章有任务在跑时按钮禁用 + 后端 409 兜底,防重复生成重复计费。
 * 需求2:生成按钮旁技能下拉,选中技能随该次生成注入提示词并进装配日志;重 roll 自动继承。
 */
const POLL_MS = 2500;

export default function WorkbenchPanel({ pid, initialNodeId }: {
  pid: string;
  initialNodeId?: string | null;   // 批次二:书况台等外部分跳转直达章
}) {
  const [chapters, setChapters] = useState<OutlineNode[]>([]);
  const [nid, setNid] = useState<string | null>(initialNodeId ?? null);
  const [preview, setPreview] = useState<WorkbenchPreview | null>(null);
  const [cs, setCs] = useState<ChangesetView | null>(null);
  const [draftText, setDraftText] = useState("");
  const [task, setTask] = useState<GenTask | null>(null);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skill, setSkill] = useState("");        // 本次生成手选技能;"" = 不启用
  // 参考提示词(2026-09-09):多选手选随草稿/自修注入;选中即用,发送后保留便于连发
  const [refItems, setRefItems] = useState<import("../types").RefPromptItem[]>([]);
  const [refIds, setRefIds] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [showAssembly, setShowAssembly] = useState(false);
  const skillTouched = useRef(false);
  const nidRef = useRef<string | null>(null);
  nidRef.current = nid;

  const loadChapters = () => {
    api.outline(pid).then((r) => {
      const chs = r.nodes.filter((n) => n.kind === "chapter");
      setChapters(chs);
      setNid((cur) => cur ?? chs[0]?.id ?? null);
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(loadChapters, [pid]);

  useEffect(() => {
    api.reviewSkills().then((r) => setSkills(r.skills)).catch(() => setSkills([]));
    // 参考提示词库(2026-09-09):长文本生成入口多选手选,优先于三层绑定
    api.settings().then((st) => setRefItems(st.reference_prompts?.items ?? [])).catch(() => {});
  }, []);

  const loadPreview = () => {
    if (!nid) return;
    api.workbenchPreview(nid, pid).then((p) => {
      setPreview(p);
      setCs(p.changeset);
      setDraftText(p.changeset?.patches?.find((x) => x.field === "content")?.after ?? "");
      // 回到本页自动续显进行中的任务(切页签/关页签再开都从这里接上)
      if (p.running_task && p.running_task.status === "running") setTask(p.running_task);
      // 技能下拉初值 = 生效默认(单本书覆盖 ?? 全局默认);用户手选过则不覆盖
      if (!skillTouched.current) setSkill(p.skill_override ?? p.skill_global ?? "");
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(loadPreview, [nid, pid]);

  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 6000);
  };
  const refresh = () => {
    loadPreview();
    loadChapters();
  };

  const submit = async (kind: "draft" | "repair") => {
    if (!nid || task) return;   // 已有任务在跑则忽略点击(防重复)
    setBusy(kind === "draft" ? "提交生成任务…" : "提交自修任务…");
    setError("");
    try {
      const r = kind === "draft"
        ? await api.generateDraft(nid, pid, skill, refIds)
        : await api.repairAsync(nid, pid, skill, refIds);
      setTask(r.task);
      flash(`任务已提交(${STAGE_LABELS[r.task.stage]});可切到其他页签,完成后自动回填。`);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  // 任务轮询:done → 回填变更集+报成本;error → 报错;只在任务属于当前章时动右侧状态
  useEffect(() => {
    if (!task || task.status !== "running") return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.workbenchTask(task.id);
        if (!alive) return;
        const t = r.task;
        setTask(t.status === "running" ? t : null);
        if (t.status === "done") {
          const res = t.result;
          const cost = t.usage_total ?? res?.usage_total ?? 0;
          if (t.node_id === nidRef.current && res?.changeset) {
            setCs(res.changeset);
            setDraftText(res.changeset.patches?.find((p) => p.field === "content")?.after ?? "");
          }
          flash(res?.note
            ? `${res.note}(¥${cost.toFixed(4)})`
            : `${t.kind === "draft" ? "草稿已生成" : "自修完成"},本次成本 ¥${cost.toFixed(4)}` +
              // 批次六乙:回执容量两值(装配 N tok·缓存 x%)
              (res?.request_tokens
                ? ` · 装配 ${res.request_tokens.toLocaleString()} tok` +
                  (res.cached_tokens ? ` · 缓存 ${Math.round((res.cached_tokens / res.request_tokens) * 100)}%` : "")
                : ""));
          setWcTick((x) => x + 1);
          refresh();
        } else if (t.status === "error") {
          setError(`生成任务失败:${t.error ?? "未知错误"}`);
        }
      } catch {
        /* 单次轮询失败忽略,下一轮重试 */
      }
    };
    const iv = setInterval(tick, POLL_MS);
    tick();
    return () => { alive = false; clearInterval(iv); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  const saveEdit = async () => {
    if (!nid || !draftText.trim()) return;
    setBusy("保存人改…");
    try {
      const view = await api.saveHumanEdit(nid, pid, draftText);
      setCs(view);
      flash("人改已保存,零 token 审计已重跑");
      setWcTick((t) => t + 1);   // 浮窗即时刷新(判据:人改保存后浮窗即时+1)
      refresh();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  const goFinalReview = async () => {
    if (!nid) return;
    try {
      await api.outlineStatus(nid, "final_review");
      flash("已转待终审(M4 终审对话台在此接力)");
      refresh();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const chapter = chapters.find((c) => c.id === nid);
  const activeValidations = cs?.validations.filter((v) => v.status !== "passed" && !v.dismissed) ?? [];
  const criticalCount = activeValidations.filter((v) => v.status === "failed").length;
  const warnCount = activeValidations.filter((v) => v.status === "warning").length;
  const patch = cs?.patches.find((p) => p.field === "content");
  const nodeTask = task && task.node_id === nid && task.status === "running" ? task : null;

  const [dismissing, setDismissing] = useState<number | null>(null);
  const [dismissNote, setDismissNote] = useState("");
  // 版本历史(C5):追加式补丁留痕,任选两版对比 + 回滚
  const [history, setHistory] = useState<PatchRow[] | null>(null);
  const [cmp, setCmp] = useState<{ a: string | null; b: string | null }>({ a: null, b: null });
  // 码字浮窗刷新信号:人改保存/任务回填后 +1,浮窗立即重拉
  const [wcTick, setWcTick] = useState(0);
  // 二期②写作区 A:并排对比 / 单栏写作(单栏给写作大画面)
  const [editMode, setEditMode] = useState<"split" | "wide">("split");

  const loadHistory = () => {
    if (!nid) { setHistory(null); return; }
    api.patchHistory(nid, pid).then((r) => setHistory(r.patches)).catch(() => setHistory(null));
  };
  useEffect(loadHistory, [nid, pid, cs?.updated_at]);

  const rollback = async (p: PatchRow) => {
    if (!nid) return;
    if (!(await uiConfirm(`回滚到 v${p.version}(${p.reason})?将以此版内容追加一个新版本,历史版本全部保留。`))) return;
    setBusy("回滚中…");
    setError("");
    try {
      const view = await api.rollbackPatch(nid, pid, p.id);
      setCs(view);
      setDraftText(view.patches?.find((x) => x.field === "content")?.after ?? "");
      const last = view.patch_history?.[view.patch_history.length - 1];
      flash(`已回滚:以 v${p.version} 内容追加 v${last?.version ?? "?"}。`);
      refresh();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  const dismiss = async (index: number) => {
    if (!dismissNote.trim() || !nid) return;
    try {
      const r = await api.dismissValidation(nid, pid, index, dismissNote.trim());
      setCs((cur) => (cur ? { ...cur, validations: r.validations } : cur));
      setDismissing(null);
      setDismissNote("");
      flash("已豁免并留痕(重审计自动延续)");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  return (
    <div>
      <WordFloat pid={pid} nid={nid} tick={wcTick} />
      <div className="row">
        <select value={nid ?? ""} onChange={(e) => setNid(e.target.value)}>
          {chapters.length === 0 && <option value="">(先在大纲树建章)</option>}
          {chapters.map((c) => (
            <option key={c.id} value={c.id}>{c.title}({c.status_label})</option>
          ))}
        </select>
        {chapter && <span className={`badge ${chapter.status === "finalized" ? "ok" : chapter.status === "unwritten" ? "" : "warn"}`}>{chapter.status_label}</span>}
        <select
          value={skill}
          disabled={!!nodeTask}
          title="本次生成/自修注入的技能(与终审台同机制:技能正文进提示词上下文)"
          onChange={(e) => { setSkill(e.target.value); skillTouched.current = true; }}
        >
          <option value="">(不启用技能)</option>
          {skills.map((s) => (
            <option key={s.key} value={s.key}>{s.name}</option>
          ))}
        </select>
        <RefPromptPicker items={refItems} selected={refIds} onChange={setRefIds} />
        <button className="primary" onClick={() => submit("draft")} disabled={!!busy || !nid || !!nodeTask}>生成草稿</button>
        {cs && <button onClick={() => submit("draft")} disabled={!!busy || !!nodeTask}>重 roll</button>}
      </div>
      {/* 二期③:章节信息卡(默认收起一行速填条;四行直写既有表) */}
      <ChapterCard pid={pid} nid={nid} onChanged={refresh} />
      {busy && <p className="muted">{busy}</p>}
      {nodeTask && (
        <div className="muted">
          <p>
            ⟳ 本章任务生成中:【{STAGE_LABELS[nodeTask.stage] ?? nodeTask.stage}】
            (切到其他页签不打断;顶栏有全局徽标,完成后本页自动回填)
          </p>
          {nodeTask.steps && nodeTask.steps.length > 0 && (
            <details className="task-steps" open>
              <summary>过程时间线(每步：环节 · 耗时 · 结果)</summary>
              <ol>
                {nodeTask.steps.map((s) => (
                  <li key={s.id} className={`task-step task-step-${s.status}`}>
                    <b>{STAGE_LABELS[s.name as GenStage] ?? s.name}</b>
                    {s.status === "running" && <span className="muted small"> 进行中…</span>}
                    {s.duration_ms != null && (
                      <span className="muted small"> {s.duration_ms >= 1000
                        ? `${(s.duration_ms / 1000).toFixed(1)}s`
                        : `${s.duration_ms}ms`}</span>
                    )}
                    {s.status === "error" && <span className="error small"> 失败</span>}
                    {s.artifact && <span className="muted small"> · {s.artifact}</span>}
                    {s.tool && <span className="muted small"> · {s.tool}</span>}
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      {!preview && <p className="muted">选择一章开始。</p>}

      {preview && (
        <>
          <h3>装配预览</h3>
          <p className="muted small">
            数字含当前生效技能的注入体积(技能不受上限裁剪);在下方临时手选其他技能时,以生成时实际为准。
          </p>
          <p className="muted small">
            {preview.assembly.total_chars} / {preview.assembly.limit_chars} 字符
            {preview.assembly.trimmed && "(超限,已按需裁剪)"}
            <button className="link" onClick={() => setShowAssembly(!showAssembly)}>
              {showAssembly ? "收起" : "展开清单"}
            </button>
          </p>
          {showAssembly && (
            <ul className="entry-list">
              {preview.assembly.sections.map((s, i) => (
                <li key={i} className={s.included ? "entry" : "entry"} style={{ opacity: s.included ? 1 : 0.45 }}>
                  <div className="entry-head">
                    <b>{s.title}</b>
                    <span className="badge">{s.source}</span>
                    <span className="badge">{s.kind === "always" ? "常驻" : "按需"}</span>
                    <span className="muted small">{s.content.length} 字</span>
                    {!s.included && <span className="badge warn">未装入</span>}
                  </div>
                  {showAssembly && <pre className="asm-content">{s.content.slice(0, 400)}{s.content.length > 400 ? "…" : ""}</pre>}
                </li>
              ))}
            </ul>
          )}

          {cs && (
            <>
              {/* 二期②写作区 A:审计默认折叠(critical 自动展开;key 使严重度翻转时重置开合) */}
              <details className="audit-fold" key={criticalCount > 0 ? "crit" : "ok"} open={criticalCount > 0}>
                <summary>
                  <h3 style={{ display: "inline", margin: 0 }}>
                    审计报告(代码检查 {criticalCount > 0 ? "未通过" : "通过"}{warnCount > 0 ? ` · ${warnCount} 条警告` : ""})
                  </h3>
                  <span className="muted small">(默认收起;点开看明细/豁免)</span>
                </summary>
              <ul className="entry-list">
                {cs.validations.map((v, i) => (
                  <li key={i} className="entry" style={v.dismissed ? { opacity: 0.45 } : undefined}>
                    <div className="entry-head">
                      <span className={v.dismissed ? "badge ok" : v.status === "failed" ? "badge warn" : v.status === "warning" ? "badge info" : "badge ok"}>
                        {v.dismissed ? "已豁免" : v.status === "failed" ? "critical" : v.status}
                      </span>
                      <b>{v.dimension ?? v.code}</b>
                      {v.auto_fixable && <span className="badge">可自动修复</span>}
                    </div>
                    <p className="small">{v.message}</p>
                    {v.dismiss_note && <p className="muted small">豁免备注:{v.dismiss_note}</p>}
                    {v.suggestion && <p className="muted small">→ {v.suggestion}</p>}
                    {v.evidence && <pre className="asm-content">{v.evidence}</pre>}
                    {!v.dismissed && (dismissing === i ? (
                      <div className="row">
                        <input
                          autoFocus
                          placeholder="豁免备注:为什么判定为误报"
                          value={dismissNote}
                          onChange={(e) => setDismissNote(e.target.value)}
                        />
                        <button className="primary" onClick={() => dismiss(i)}>确认豁免</button>
                        <button onClick={() => setDismissing(null)}>取消</button>
                      </div>
                    ) : (
                      <button className="link" onClick={() => { setDismissing(i); setDismissNote(""); }}>人工豁免(误报)</button>
                    ))}
                  </li>
                ))}
                {cs.validations.length === 0 && <li className="muted">九类检查全部通过,零 token。</li>}
              </ul>

              {cs.review && (cs.review as { review_error?: string }).review_error && (
                <>
                  <h3>AI 评审(第二道)</h3>
                  <p className="badge warn">评审调用失败:{(cs.review as { review_error?: string }).review_error}(advisory 不阻塞;可重 roll 重新生成并评审)</p>
                </>
              )}
              {cs.review && !(cs.review as { review_error?: string }).review_error && (
                <>
                  <h3>AI 评审(第二道)</h3>
                  <p className="small">
                    {Object.entries((cs.review.scores ?? {}) as Record<string, { score: number; note: string }>)
                      .map(([k, v]) => `${k} ${v.score}`).join(" · ")}
                  </p>
                  {(cs.review.findings as { quote: string; issue: string; suggestion: string }[] | undefined)?.map((f, i) => (
                    <p key={i} className="small">「{f.quote}」— {f.issue} → {f.suggestion}</p>
                  ))}
                  {(cs.review as { parse_error?: boolean }).parse_error && (
                    <p className="muted small">评审回包为空或解析失败(不阻塞;可重 roll 或忽略)。</p>
                  )}
                </>
              )}
              </details>

              {/* 二期②写作区 A:并排对比 / 单栏写作 切换(单栏给写作大画面) */}
              <div className="row spread" style={{ margin: "8px 0 0" }}>
                <h3 style={{ margin: 0 }}>
                  人改工作区({editMode === "split" ? "左右分栏" : "单栏写作"})
                </h3>
                <span>
                  <button className={editMode === "split" ? "active" : ""}
                    onClick={() => setEditMode("split")}>并排对比</button>
                  <button className={editMode === "wide" ? "active" : ""}
                    onClick={() => setEditMode("wide")}>单栏写作</button>
                </span>
              </div>
              <div className={editMode === "wide" ? "wide-edit" : "diff-grid"}>
                {editMode === "split" && (
                  <div>
                    <p className="muted small">正式正文(第 {preview.revision} 版)</p>
                    <pre className="diff-pane">{preview.current_text || "(空,本章尚无定稿)"}</pre>
                  </div>
                )}
                <div>
                  {editMode === "split"
                    ? <p className="muted small">当前草稿(可直接编辑保存人改)</p>
                    : <p className="muted small">当前草稿(单栏写作;正式正文第 {preview.revision} 版切「并排对比」可见)</p>}
                  <textarea
                    className="diff-edit"
                    rows={18}
                    value={draftText}
                    onChange={(e) => setDraftText(e.target.value)}
                  />
                </div>
              </div>
              <div className="row">
                <button onClick={saveEdit} disabled={!!busy}>保存人改</button>
                <button onClick={() => submit("repair")} disabled={!!busy || !!nodeTask}>AI 自修一轮</button>
                {chapter?.status === "human_editing" && criticalCount === 0 && (
                  <button className="primary" onClick={goFinalReview} disabled={!!busy}>通过 → 待终审</button>
                )}
                {criticalCount > 0 && (
                  <span className="badge warn">{criticalCount} 个 critical 未清零,不允许合入</span>
                )}
                {patch && <span className="muted small">来源:{patch.reason}</span>}
              </div>

              {history && history.length > 0 && (
                <>
                  <h3>版本历史(追加式留痕)</h3>
                  <p className="muted small">
                    生成/重 roll/人改/自修/采纳每次追加一版,永不覆盖;点 A、B 选两版并排对比,可回滚。
                  </p>
                  <table>
                    <thead>
                      <tr><th>版本</th><th>来源</th><th>时间(UTC)</th><th>字数</th><th>对比</th><th>操作</th></tr>
                    </thead>
                    <tbody>
                      {history.map((p) => (
                        <tr key={p.id}>
                          <td>
                            v{p.version}
                            {p.version === history[history.length - 1].version && (
                              <span className="badge info"> 当前</span>
                            )}
                          </td>
                          <td>{p.reason}</td>
                          <td className="muted small">{(p.created_at ?? "").replace("T", " ").slice(0, 16)}</td>
                          <td>{(p.after ?? "").length}</td>
                          <td>
                            <button className={cmp.a === p.id ? "link active-cmp" : "link"}
                              title="选为对比左栏(A)"
                              onClick={() => setCmp((c) => ({ ...c, a: p.id }))}>A</button>
                            <button className={cmp.b === p.id ? "link active-cmp-b" : "link"}
                              title="选为对比右栏(B)"
                              onClick={() => setCmp((c) => ({ ...c, b: p.id }))}>B</button>
                          </td>
                          <td>
                            <button className="link" onClick={() => rollback(p)}>回滚到此版</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {cmp.a && cmp.b && (
                    <DiffTwoPane
                      left={history.find((x) => x.id === cmp.a)!}
                      right={history.find((x) => x.id === cmp.b)!}
                    />
                  )}
                </>
              )}
            </>
          )}

          {!cs && (
            <p className="muted">
              本章还没有草稿。点「生成草稿」:后台自动生成计划卡 → 装配上下文 → 写稿 → 字数规整 →
              代码层九类审计 + AI 评审,全程记账;生成中可切页签,顶栏徽标可见进度。
            </p>
          )}
        </>
      )}
    </div>
  );
}


// ── 两版并排对比(C5;自研薄实现,开源参考搜索结论见执行书汇总:C 档带过)──

type DiffRow = { l: string | null; r: string | null; kind: "same" | "del" | "add" };

/** 中文正文按行切几乎整章一行,先做对比粒度规整:短行原样,长段按句聚合到约 50 字。 */
function splitForDiff(text: string): string[] {
  const out: string[] = [];
  for (const para of text.split("\n")) {
    if (!para.length) continue;
    if (para.length <= 60) { out.push(para); continue; }
    const sentences = para.match(/[^。!?…”"」』]+[。!?…”"」』]*/g) ?? [para];
    let buf = "";
    for (const s of sentences) {
      buf += s;
      if (buf.length >= 50) { out.push(buf); buf = ""; }
    }
    if (buf) out.push(buf);
  }
  return out;
}

function diffLines(a: string, b: string): DiffRow[] {
  const as = splitForDiff(a);
  const bs = splitForDiff(b);
  const n = as.length, m = bs.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = as[i] === bs[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (as[i] === bs[j]) { rows.push({ l: as[i], r: bs[j], kind: "same" }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { rows.push({ l: as[i], r: null, kind: "del" }); i++; }
    else { rows.push({ l: null, r: bs[j], kind: "add" }); j++; }
  }
  while (i < n) { rows.push({ l: as[i], r: null, kind: "del" }); i++; }
  while (j < m) { rows.push({ l: null, r: bs[j], kind: "add" }); j++; }
  return rows;
}

function DiffTwoPane({ left, right }: { left: PatchRow; right: PatchRow }) {
  const rows = diffLines(left.after ?? "", right.after ?? "");
  return (
    <div className="diff-two">
      <p className="muted small">
        对比:v{left.version}({left.reason}) ←→ v{right.version}({right.reason});
        左栏独有 = 红,右栏独有 = 绿。
      </p>
      <table className="diff-table">
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={row.kind === "del" ? "del" : row.kind === "add" ? "add" : ""}>
              <td>{row.l ?? ""}</td>
              <td>{row.r ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
