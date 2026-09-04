import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  AttachmentRef, ChatMessage, ChatRefs, ConversationSession, GenTask, OutlineNode, Suggestion,
} from "../types";

/**
 * 统一对话组件(A3,执行书 2026-08-31):
 * 终审对话台 / 测试对话 / 大纲节点抽屉对话共用,仅上下文预设不同。
 * - 多线会话:每节点可开多条命名对话线(会话线切换 + 新建);
 * - 发送即任务化(A4 拍板,不做流式):提交拿任务号 → 轮询 → 完成回填;
 *   切走再切回由全局任务列表按 session_id 恢复进度,不丢状态;
 * - 建议块(A1):assistant 消息里的结构化建议渲染卡片,[采纳] 分流两档:
 *   outline_field 轻档 = 弹改前/改后 diff,人确认后写回节点字段(留痕);
 *   chapter_text 重档 = 起草修改进该章工作台变更集(AI 自修同管道);
 * - @引用(A2):章/角色/条目/伏笔 chips 随消息附加,扩展终审台章节附件机制。
 */
const POLL_MS = 2500;

export interface ChatPanelProps {
  projectId: string | null;
  ownerType: "review" | "chat_test" | "outline_node" | "branch" | "timeline_event"
    | "graph_node" | "graph_edge" | "graph_board" | "book";
  ownerId: string | null;         // review=章节点;outline_node=节点;branch=主干节点;图谱对象=id
  defaultSessionName: string;     // 首条对话线的预填名
  allowSkill?: boolean;
  allowTemp?: boolean;
  allowRefs?: boolean;            // 显示 @章/@角色/@条目/@伏笔 选择器
  allowPresets?: boolean;         // 显示预设按钮(C3 节点对话;组可经 presets 换)
  presets?: { key: string; label: string; hint: string }[];  // 预设组覆盖(书级=起步方向卡)
  sessionId?: string | null;      // 直连指定会话(分支视图):隐藏线选择与新建
  emptyHint?: string;
  onAdopted?: (target: string) => void;   // 采纳成功后通知父组件刷新
  // 轻档采纳取"改前值"的回调(event_field 等对象字段):返回空串=无改前
  getAdoptBefore?: (s: Suggestion) => string;
  getAdoptAnchor?: (s: Suggestion) => { x: number; y: number } | null;
}

const SEVERITY_CLASS: Record<string, string> = {
  critical: "badge warn", major: "badge info", minor: "badge",
};
const TARGET_LABEL: Record<string, string> = {
  outline_field: "大纲字段", chapter_text: "正文修改", none: "仅提示",
  event_field: "事件字段",
};
const PRESETS = [
  { key: "optimize", label: "优化", hint: "点选后发送:针对当前节点给具体改法(outline_field 建议)" },
  { key: "ideas", label: "奇思妙想", hint: "点选后发送:发散 3-5 个互不重复的创作方向" },
];

export default function ChatPanel({
  projectId, ownerType, ownerId, defaultSessionName,
  allowSkill, allowTemp, allowRefs, allowPresets, sessionId, emptyHint, onAdopted,
  getAdoptBefore,
  getAdoptAnchor,
  presets = PRESETS,
}: ChatPanelProps) {
  const [sessions, setSessions] = useState<ConversationSession[] | null>(null);
  const [sid, setSid] = useState<string | null>(sessionId ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [skills, setSkills] = useState<{ key: string; name: string; description: string }[]>([]);
  const [skill, setSkill] = useState("");
  const [temp, setTemp] = useState("0.7");
  const [preset, setPreset] = useState<string | null>(null);
  const [task, setTask] = useState<GenTask | null>(null);      // 本会话进行中的发送任务
  const [chips, setChips] = useState<AttachmentRef[]>([]);
  const [refs, setRefs] = useState<ChatRefs | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTab, setPickerTab] = useState<"chapter" | "entry" | "hook">("chapter");
  const [newLineOpen, setNewLineOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [nodes, setNodes] = useState<OutlineNode[]>([]);        // 轻档采纳取改前值用
  const [adopting, setAdopting] = useState<{ msgId: string; idx: number } | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const taskRef = useRef(task);
  taskRef.current = task;

  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 6000);
  };

  const loadSessions = () => {
    if (sessionId) { setSid(sessionId); return; }   // 直连模式:分支视图固定一条会话
    api.conversations({
      owner_type: ownerType,
      owner_id: ownerId ?? "",
      project_id: projectId ?? undefined,
    }).then((r) => {
      setSessions(r.sessions);
      setSid((cur) => (cur && r.sessions.some((s) => s.id === cur) ? cur : r.sessions[0]?.id ?? null));
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(loadSessions, [ownerType, ownerId, projectId, sessionId]);

  const loadMessages = () => {
    if (!sid) { setMessages([]); return; }
    api.conversationMessages(sid).then((r) => setMessages(r.messages)).catch(() => {});
  };
  useEffect(loadMessages, [sid]);

  useEffect(() => {
    if (allowSkill) api.reviewSkills().then((r) => setSkills(r.skills)).catch(() => setSkills([]));
    if (allowRefs && projectId) {
      api.chatRefs(projectId).then(setRefs).catch(() => setRefs(null));
      api.outline(projectId).then((r) => setNodes(r.nodes)).catch(() => setNodes([]));
    }
    setChips([]);
    setPickerOpen(false);
  }, [projectId, ownerType]);

  // 切线时恢复进行中的发送任务(live/replay 同源:任何时刻查都有完整状态)
  useEffect(() => {
    setTask(null);
    if (!sid) return;
    api.activeGenTasks().then((r) => {
      const running = r.tasks.find((t) => t.kind === "chat" && t.session_id === sid);
      if (running) setTask(running);
    }).catch(() => {});
  }, [sid]);

  // 任务轮询:done → 回填消息 + 报成本;error → 报错
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
          loadMessages();
          flash(`回包完成,本次 ¥${(t.usage_total ?? 0).toFixed(4)}`);
        } else if (t.status === "error") {
          setError(`消息生成失败:${t.error ?? "未知错误"}`);
        }
      } catch { /* 单次轮询失败忽略,下一轮重试 */ }
    };
    const iv = setInterval(tick, POLL_MS);
    tick();
    return () => { alive = false; clearInterval(iv); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  const createLine = async () => {
    if (!newName.trim()) return;
    try {
      const r = await api.createConversation({
        project_id: projectId, owner_type: ownerType, owner_id: ownerId ?? "",
        name: newName.trim(),
      });
      setNewLineOpen(false);
      setNewName("");
      setSessions((cur) => [...(cur ?? []), r.session]);
      setSid(r.session.id);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const send = async () => {
    if (!sid || !input.trim() || task) return;
    setError("");
    try {
      const r = await api.sendConversationMessage(sid, {
        message: input.trim(),
        skill: allowSkill && skill ? skill : null,
        temperature: allowTemp && temp ? Number(temp) : null,
        attachments: chips,
        preset: preset ?? null,
      });
      setInput("");
      setChips([]);
      setPreset(null);   // 预设只作用于本次请求,发完即清
      setTask(r.task);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const addChip = (ref: AttachmentRef) => {
    setChips((cur) =>
      cur.some((c) => c.type === ref.type && c.id === ref.id) ? cur : [...cur, ref]);
    setPickerOpen(false);
  };

  // ── 采纳(A-采纳规则:轻档三类 + 重档正文)──
  const [adoptBeforeText, setAdoptBeforeText] = useState("");
  const beginAdopt = (m: ChatMessage, idx: number) => {
    const s = m.meta?.suggestions?.[idx];
    if (s && getAdoptBefore) setAdoptBeforeText(getAdoptBefore(s));
    else setAdoptBeforeText("");
    setAdopting({ msgId: m.id, idx });
    if (allowRefs && projectId && nodes.length === 0) {
      api.outline(projectId).then((r) => setNodes(r.nodes)).catch(() => {});
    }
  };

  const confirmAdopt = async (m: ChatMessage, idx: number, _s: Suggestion) => {
    if (!sid) return;
    setError("");
    try {
      const sug = m.meta?.suggestions?.[idx];
      const anchor = sug && getAdoptAnchor ? getAdoptAnchor(sug) : null;
      const r = await api.adoptSuggestion({ session_id: sid, message_id: m.id, index: idx, anchor });
      setAdopting(null);
      flash(r.summary || "已采纳");
      loadMessages();          // 刷新:该建议卡转"已采纳"钉住
      onAdopted?.(r.target);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const adoptingMsg = adopting ? messages.find((m) => m.id === adopting.msgId) : null;
  const adoptingSug = adoptingMsg && adopting
    ? adoptingMsg.meta?.suggestions?.[adopting.idx] : null;
  const adoptItem = (adoptingSug?.target?.item ?? {}) as {
    type?: string; label?: string; sub_label?: string;
    from_node_id?: string; to_node_id?: string; kind?: string;
  };
  const adoptingNode = adoptingSug?.target?.node_id
    ? nodes.find((n) => n.id === adoptingSug.target?.node_id) : null;

  return (
    <div className="chat-panel">
      {!sessionId && (
        <div className="row spread">
          <div className="row" style={{ margin: 0, flex: 1 }}>
            <select
              value={sid ?? ""}
              onChange={(e) => setSid(e.target.value || null)}
              title="对话线(同一节点可开多条命名会话)"
            >
              {(sessions ?? []).map((s) => (
                <option key={s.id} value={s.id}>{s.name}({s.message_count})</option>
              ))}
              {(sessions ?? []).length === 0 && <option value="">(还没有对话线)</option>}
            </select>
            <button className="link" onClick={() => { setNewLineOpen(!newLineOpen); setNewName(defaultSessionName); }}>
              +新对话线
            </button>
            {allowSkill && (
              <select value={skill} onChange={(e) => setSkill(e.target.value)} title="技能">
                <option value="">(不启用技能)</option>
                {skills.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
              </select>
            )}
            {allowTemp && (
              <input className="w-temp" type="number" step="0.1" value={temp}
                onChange={(e) => setTemp(e.target.value)} title="温度" />
            )}
          </div>
        </div>
      )}
      {!sessionId && newLineOpen && (
        <div className="row">
          <input autoFocus placeholder="新对话线名称" value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") createLine(); }} />
          <button className="primary" onClick={createLine}>开线</button>
          <button onClick={() => setNewLineOpen(false)}>取消</button>
        </div>
      )}
      {emptyHint && messages.length === 0 && !task && <p className="muted small">{emptyHint}</p>}
      {/* 起步方向卡(书级对话空态,骨架批执行书 §2):点击选中预设,输入后发送 */}
      {allowPresets && messages.length === 0 && !task && presets.length > 0 && (
        <div className="dir-cards">
          {presets.map((p) => (
            <button key={p.key} className={preset === p.key ? "on" : ""}
              onClick={() => setPreset(preset === p.key ? null : p.key)}>
              <b>{p.label}</b>
              <span className="small">{p.hint}</span>
            </button>
          ))}
        </div>
      )}

      <div className="chat-history">
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "chat-msg user" : "chat-msg"}>
            <p className="muted small">
              {m.role === "user" ? "我" : (m.meta?.model ? `主编(${m.meta.model})` : "主编")}
              {" · "}{m.created_at.replace("T", " ").slice(0, 16)}(UTC)
              {m.role === "assistant" && m.meta?.cost != null && ` · ¥${m.meta.cost.toFixed(4)}`}
            </p>
            {m.content && <pre>{m.content}</pre>}
            {m.role === "assistant" && m.meta?.parse_error && (
              <p className="muted small">⚠ 结构化解析失败,已按纯文本保留原回包(可重发一次)。</p>
            )}
            {(m.meta?.suggestions ?? []).map((s, i) => (
              <SuggestionCard
                key={i}
                s={s}
                canAdoptOutline={!!projectId}
                adopting={adopting?.msgId === m.id && adopting?.idx === i}
                onBegin={() => beginAdopt(m, i)}
              />
            ))}
          </div>
        ))}
        {task && task.status === "running" && (
          <p className="muted">⟳ 消息生成中(可切页签,完成后自动回填)…</p>
        )}
      </div>

      {/* graph_add 批准闸门:预览将新增的节点/连线,人确认才落库(第四批 D) */}
      {adopting && adoptingSug && adoptingSug.target_type === "graph_add" && (
        <div className="dialog">
          <p><b>采纳新增建议(批准闸门)</b>:确认后将在图谱板新增:</p>
          {adoptItem.type === "node" && (
            <p className="small">
              方框节点:<b>{adoptItem.label}</b>
              {adoptItem.sub_label ? `(${adoptItem.sub_label})` : ""}
              —— 自动放到网格空位
            </p>
          )}
          {adoptItem.type === "edge" && (
            <p className="small">
              连线:{String(adoptItem.from_node_id ?? "").slice(0, 14)}…
              {" --["}{String(adoptItem.kind ?? "")}
              {adoptItem.label ? `·${String(adoptItem.label)}` : ""}{"]--> "}
              {String(adoptItem.to_node_id ?? "").slice(0, 14)}…
            </p>
          )}
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认新增
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
      {adopting && adoptingSug && adoptingSug.target_type === "graph_field" && (
        <div className="dialog">
          <p><b>采纳图谱字段建议(轻档)</b>:确认后写回并留痕。</p>
          <p className="small">字段:<b>{adoptingSug.target?.field}</b></p>
          <div className="diff-grid">
            <div>
              <p className="muted small">改前</p>
              <pre className="diff-pane">{adoptBeforeText || "(空)"}</pre>
            </div>
            <div>
              <p className="muted small">改后</p>
              <pre className="diff-pane">{adoptingSug.target?.value || "(空)"}</pre>
            </div>
          </div>
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认写回
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
      {/* 轻档采纳确认:改前/改后 diff → 人确认写回(A-采纳规则) */}
      {adopting && adoptingSug && (adoptingSug.target_type === "outline_field"
        || adoptingSug.target_type === "event_field") && (
        <div className="dialog">
          <p><b>采纳字段建议(轻档)</b>:确认后写回并留痕。</p>
          <p className="small">
            {adoptingSug.target_type === "outline_field" && (
              <>节点:<b>{adoptingNode?.title ?? adoptingSug.target?.node_id ?? "?"}</b> · </>
            )}
            字段:<b>{adoptingSug.target?.field}</b>
            {adoptingSug.target_type === "outline_field" && !adoptingNode && (
              <span className="muted">(节点信息加载中,或该节点不在本书大纲)</span>
            )}
          </p>
          <div className="diff-grid">
            <div>
              <p className="muted small">改前</p>
              <pre className="diff-pane">{adoptBeforeText || "(空)"}</pre>
            </div>
            <div>
              <p className="muted small">改后</p>
              <pre className="diff-pane">{adoptingSug.target?.value || "(空)"}</pre>
            </div>
          </div>
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认写回
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
      {adopting && adoptingSug && adoptingSug.target_type === "chapter_text" && (
        <div className="dialog">
          <p><b>采纳正文建议(重档)</b>:AI 的修改段落将作为新版本进入该章工作台变更集,
            在人改区核对后再合入,不会直接改正文。</p>
          <pre className="asm-content">{(adoptingSug.target?.revised_text || "").slice(0, 600)}
            {(adoptingSug.target?.revised_text || "").length > 600 ? "…" : ""}</pre>
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认进变更集
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}

      {allowPresets && (
        <div className="ref-bar">
          <span className="muted small">预设模式:</span>
          {presets.map((p) => (
            <button key={p.key} title={p.hint}
              className={`chip ${preset === p.key ? "on" : ""}`}
              onClick={() => setPreset(preset === p.key ? null : p.key)}>
              {p.label}
            </button>
          ))}
          {preset && (
            <span className="muted small">已选「{presets.find((x) => x.key === preset)?.label}」,输入后发送;再次点击取消。</span>
          )}
        </div>
      )}

      {allowRefs && (
        <div className="ref-bar">
          {chips.map((c, i) => (
            <span key={i} className="badge info ref-chip" title="随下一条消息附加的上下文">
              @{c.label}
              <button className="link" onClick={() => setChips(chips.filter((_, j) => j !== i))}>×</button>
            </span>
          ))}
          <button className="link" onClick={() => setPickerOpen(!pickerOpen)} disabled={!refs}>@引用</button>
        </div>
      )}
      {pickerOpen && refs && (
        <div className="dialog ref-picker">
          <div className="row">
            {(["chapter", "entry", "hook"] as const).map((t) => (
              <button key={t} className={pickerTab === t ? "active" : ""}
                onClick={() => setPickerTab(t)}>
                {t === "chapter" ? "章" : t === "entry" ? "角色/条目" : "伏笔"}
              </button>
            ))}
            <span className="spread" />
            <button className="link" onClick={() => setPickerOpen(false)}>收起</button>
          </div>
          <ul className="entry-list">
            {pickerTab === "chapter" && refs.chapters.map((c) => (
              <li key={c.id} className="entry entry-head">
                <b>{c.title}</b>
                <span className="badge">{c.status}</span>
                <button className="link" onClick={() => addChip({ type: "chapter", id: c.id, label: c.title })}>引用</button>
              </li>
            ))}
            {pickerTab === "entry" && refs.entries.map((e) => (
              <li key={e.id} className="entry entry-head">
                <span className="badge">{e.category}</span>
                <b>{e.name}</b>
                <button className="link" onClick={() => addChip({ type: "entry", id: e.id, label: e.name })}>引用</button>
              </li>
            ))}
            {pickerTab === "hook" && refs.hooks.length === 0 && <li className="muted small">伏笔池为空。</li>}
            {pickerTab === "hook" && refs.hooks.map((h, i) => (
              <li key={i} className="entry entry-head">
                <span className="badge">{h.status}</span>
                <span className="small">{h.detail.slice(0, 60)}{h.detail.length > 60 ? "…" : ""}</span>
                <button className="link"
                  onClick={() => addChip({ type: "hook", label: h.detail.slice(0, 120) })}>引用</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="row">
        <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)}
          placeholder={allowRefs
            ? "对审稿主编说点什么;@引用 可附加章/角色/条目/伏笔上下文"
            : "对模型说点什么…"} />
        <button className="primary" onClick={send} disabled={!!task || !sid || !input.trim()}>
          {task ? "生成中…" : "发送"}
        </button>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function SuggestionCard({ s, canAdoptOutline, adopting, onBegin }: {
  s: Suggestion;
  canAdoptOutline: boolean;
  adopting: boolean;
  onBegin: () => void;
}) {
  const adoptable = !s.adopted && s.target_type !== "none"
    && (s.target_type !== "outline_field" || canAdoptOutline);
  return (
    <div className={`sug-card${s.adopted ? " adopted" : ""}`}>
      <div className="entry-head">
        <span className={SEVERITY_CLASS[s.severity] ?? "badge"}>{s.severity}</span>
        <span className="badge">{TARGET_LABEL[s.target_type] ?? s.target_type}</span>
        {s.target_type === "outline_field" && s.target?.field && (
          <span className="badge">{s.target.field}</span>
        )}
        {s.adopted && <span className="badge ok">已采纳{s.adopt_summary ? ` · ${s.adopt_summary}` : ""}</span>}
      </div>
      {s.quote && <pre className="asm-content">「{s.quote}」</pre>}
      {s.issue && <p className="small">{s.issue}</p>}
      {s.suggestion && <p className="small ok">→ {s.suggestion}</p>}
      {adoptable && !adopting && <button className="link" onClick={onBegin}>采纳</button>}
    </div>
  );
}
