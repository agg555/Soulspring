import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  AttachmentRef, ChatMessage, ChatRefs, ConversationSession, GenTask, OutlineNode,
  PromptTemplate, RefPromptItem, SubtopicItem, Suggestion,
} from "../types";
import RefPromptPicker from "./RefPromptPicker";
import ChatHistory from "./chat/ChatHistory";
import ChatAdoptDialogs from "./chat/ChatAdoptDialogs";
import ChatRefPicker from "./chat/ChatRefPicker";
import {
  TEMPLATE_QUESTIONS, TemplateFillDialog, TemplateManagerDialog, type FillChip,
  fillTemplateText,
} from "./PromptTemplates";

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
    | "graph_node" | "graph_edge" | "graph_board" | "book" | "l1" | "idea";
  ownerId: string | null;         // review=章节点;outline_node=节点;branch=主干节点;图谱对象=id;idea=构思
  defaultSessionName: string;     // 首条对话线的预填名
  allowSkill?: boolean;
  allowTemp?: boolean;
  allowRefs?: boolean;            // 显示 @章/@角色/@条目/@伏笔 选择器
  allowPresets?: boolean;         // 显示预设按钮(C3 节点对话;组可经 presets 换)
  presets?: { key: string; label: string; hint: string }[];  // 预设组覆盖(书级=起步方向卡)
  initialPreset?: string | null;   // 外部直选预设(大纲树"AI 体检"等跳入;配合 key 重挂)
  onOpenNode?: (nid: string) => void;   // 建议块"📍节点"直达(体感 2026-09-06:免一个个找)
  sessionId?: string | null;      // 直连指定会话(分支视图):隐藏线选择与新建
  emptyHint?: string;
  onAdopted?: (target: string) => void;   // 采纳成功后通知父组件刷新
  // 轻档采纳取"改前值"的回调(event_field 等对象字段):返回空串=无改前
  getAdoptBefore?: (s: Suggestion) => string;
  getAdoptAnchor?: (s: Suggestion) => { x: number; y: number } | null;
}

// 模型上下文窗口表(体感 2026-09-06"上下文百分比"显示;来源=备忘-模型实测+用户提供的官方规格;
// 新模型在此登记,未知模型不显示百分比)
const CONTEXT_WINDOW: Array<[string, number]> = [
  ["glm", 1_048_576],          // glm-5.3-flash:1M(精确 1,048,576),输出 128K
  ["deepseek", 1_048_576],     // deepseek-v4-flash:1M,输出 384K
];
function contextWindowOf(model: string | undefined): number | null {
  if (!model) return null;
  const m = model.toLowerCase();
  for (const [key, size] of CONTEXT_WINDOW) if (m.includes(key)) return size;
  return null;
}

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
  initialPreset = null,
  onOpenNode,
}: ChatPanelProps) {
  const [sessions, setSessions] = useState<ConversationSession[] | null>(null);
  const [sid, setSid] = useState<string | null>(sessionId ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [skills, setSkills] = useState<{ key: string; name: string; description: string }[]>([]);
  const [skill, setSkill] = useState("");
  const [temp, setTemp] = useState("0.7");
  const [thinking, setThinking] = useState("");   // 空=按动作档位
  const [preset, setPreset] = useState<string | null>(initialPreset);
  const [task, setTask] = useState<GenTask | null>(null);      // 本会话进行中的发送任务
  const [chips, setChips] = useState<AttachmentRef[]>([]);
  const [refs, setRefs] = useState<ChatRefs | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTab, setPickerTab] = useState<"chapter" | "entry" | "hook">("chapter");
  const [newLineOpen, setNewLineOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [nodes, setNodes] = useState<OutlineNode[]>([]);        // 轻档采纳取改前值用
  const [ctxModel, setCtxModel] = useState<string | undefined>(undefined);  // 上下文占用显示用
  // 批次三③去太极客:工程信息常显开关(默认关=大众视图;localStorage 全局偏好)
  const [showEng, setShowEng] = useState(() => {
    try { return localStorage.getItem("chat:showEngineering") === "1"; } catch { return false; }
  });
  const [ctxMsg, setCtxMsg] = useState("");   // ⑤压缩/提示瞬态
  const fileInputRef = useRef<HTMLInputElement | null>(null);   // ①附件按钮(txt/md)
  const [adopting, setAdopting] = useState<{ msgId: string; idx: number } | null>(null);
  // subtopic_add 闸门:人在弹窗里增删改后的树(批准时覆盖 meta 原树)
  const [subtreeEdit, setSubtreeEdit] = useState<SubtopicItem[] | null>(null);
  // 选择填空式模板(2026-09-09):点 chip 弹填空表单;用户模板存 settings 全局共用
  const [userTpls, setUserTpls] = useState<PromptTemplate[]>([]);
  const [fillChip, setFillChip] = useState<FillChip | null>(null);
  const [mgrOpen, setMgrOpen] = useState(false);
  // 参考提示词(2026-09-10 扩到对话线):多选手选随消息注入(仅手选生效)
  const [refItems, setRefItems] = useState<RefPromptItem[]>([]);
  const [refIds, setRefIds] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const taskRef = useRef(task);
  taskRef.current = task;

  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 6000);
  };

  // 批次七⑤:建议卡「💭下钻」——建议登记为构思树根节点并开子讨论线;
  // 通过 CustomEvent 通知面板宿主切到「构思」页签并打开该子线对话框。
  const drillIdea = async (m: ChatMessage, idx: number, s: Suggestion) => {
    if (!projectId || !sid) return;
    const title = (s.suggestion || s.issue || "未命名构思").slice(0, 60);
    try {
      const r = await api.ideasCreate({
        pid: projectId, title,
        source_ref: { session_id: sid, message_id: m.id, idx },
      });
      window.dispatchEvent(new CustomEvent("soulspring:idea-drill", { detail: r.idea.id }));
      flash(`已下钻为构思「${r.idea.title}」,子讨论线已打开`);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
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
    api.settings().then((st) => {
      setCtxModel(st.llm?.model);
      setUserTpls(st.prompt_templates?.items ?? []);
      setRefItems(st.reference_prompts?.items ?? []);
    }).catch(() => {});
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

  const send = async (opts?: { preset?: string | null; presetText?: string | null; message?: string }) => {
    const text = (opts?.message ?? input).trim();
    if (!text || task) return;
    setError("");
    try {
      // 体感 2026-09-06:空态(还没有对话线)回车/发送自动开线,不再让人卡在"先开线"
      let targetSid = sid;
      if (!targetSid) {
        const created = await api.createConversation({
          project_id: projectId, owner_type: ownerType, owner_id: ownerId ?? "",
          name: (opts?.preset ?? preset)
            ? presets.find((x) => x.key === (opts?.preset ?? preset))?.label ?? defaultSessionName
            : defaultSessionName,
        });
        targetSid = created.session.id;
        setSessions((cur) => [...(cur ?? []), created.session]);
        setSid(targetSid);
      }
      const r = await api.sendConversationMessage(targetSid, {
        message: text,
        skill: allowSkill && skill ? skill : null,
        temperature: allowTemp && temp ? Number(temp) : null,
        thinking: thinking || null,
        attachments: chips,
        preset: opts?.preset !== undefined ? opts.preset : (preset ?? null),
        preset_text: opts?.presetText ?? null,
        ref_prompt_ids: refIds.length ? refIds : null,
      });
      setInput("");
      setChips([]);
      setPreset(null);   // 预设只作用于本次请求,发完即清
      setTask(r.task);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  // 填空模板确认:组装答案 → 按 preset/自定义两态发送。输入框有字=消息正文照发
  // (模板指令叠加);为空=以模板名占位作消息正文(指令已在 system 表达意图)。
  const sendFilled = async (answers: string[]) => {
    if (!fillChip || task) return;
    const text = fillTemplateText(fillChip.questions, answers);
    const opt = {
      preset: fillChip.builtin ? fillChip.key : null,
      presetText: text || null,
      message: input.trim() || `【${fillChip.name}】请按模板指令执行`,
    };
    setFillChip(null);
    await send(opt);
  };

  // 模板管理保存:全量替换(后端校验兜底,失败原样抛给弹窗显示)
  const saveTemplates = async (items: PromptTemplate[]) => {
    const r = await api.putPromptTemplates(items);
    setUserTpls(r.prompt_templates.items);
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
    // subtopic_add:编辑树初始=AI 建议树(人在闸门窗可增删改)
    setSubtreeEdit(s?.target_type === "subtopic_add" ? (s.target?.tree ?? []) : null);
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
      const r = await api.adoptSuggestion({
        session_id: sid, message_id: m.id, index: idx, anchor,
        tree: sug?.target_type === "subtopic_add" ? (subtreeEdit ?? undefined) : undefined,
      });
      setAdopting(null);
      setSubtreeEdit(null);
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
            <select value={thinking} style={{ fontSize: 12 }}
              onChange={(e) => setThinking(e.target.value)}
              title="思考程度:默认=按动作档位;关=DeepSeek 非思考(提速省费),GLM 回落默认">
              <option value="">思考:默认</option>
              <option value="off">思考:关(DeepSeek 非思考)</option>
              <option value="low">思考:低</option>
              <option value="high">思考:高</option>
              <option value="max">思考:最大</option>
            </select>
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

      <ChatHistory
        messages={messages} showEng={showEng} task={task} projectId={projectId}
        adopting={adopting} beginAdopt={beginAdopt} onOpenNode={onOpenNode}
        drillIdea={drillIdea} />

      {/* 采纳批准闸门五弹窗(graph_add/subtopic_add/graph_field/轻档字段/chapter_text) */}
      <ChatAdoptDialogs
        adopting={adopting} adoptingMsg={adoptingMsg} adoptingSug={adoptingSug}
        adoptItem={adoptItem} adoptingNode={adoptingNode} adoptBeforeText={adoptBeforeText}
        subtreeEdit={subtreeEdit} confirmAdopt={confirmAdopt}
        setAdopting={setAdopting} setSubtreeEdit={setSubtreeEdit} />

      {allowPresets && (() => {
        // 有问题定义的内置 preset + 用户模板 → 弹填空表单;其余(书级方向卡)保持老点击
        const tplChips: FillChip[] = [
          ...presets.filter((p) => TEMPLATE_QUESTIONS[p.key]).map((p) => ({
            key: p.key, name: p.label, builtin: true, questions: TEMPLATE_QUESTIONS[p.key],
          })),
          ...userTpls.map((t) => ({
            key: t.id, name: t.name, builtin: false, questions: t.questions,
          })),
        ];
        const plainPresets = presets.filter((p) => !TEMPLATE_QUESTIONS[p.key]);
        return (
          <div className="ref-bar">
            <span className="muted small">预设模板:</span>
            {tplChips.map((c) => (
              <button key={c.key} title={`「${c.name}」:弹出模板,逐条填空后发送`}
                className={`chip ${preset === c.key ? "on" : ""}`}
                onClick={() => setFillChip(c)}>
                {c.name}
              </button>
            ))}
            {plainPresets.map((p) => (
              <button key={p.key} title={p.hint}
                className={`chip ${preset === p.key ? "on" : ""}`}
                onClick={() => setPreset(preset === p.key ? null : p.key)}>
                {p.label}
              </button>
            ))}
            <button className="link" title="管理我的模板(新建/编辑/删除,全部对话入口共用)"
              onClick={() => setMgrOpen(true)}>⚙ 模板</button>
            {refItems.length > 0 && (
              <RefPromptPicker items={refItems} selected={refIds} onChange={setRefIds} />
            )}
            {preset && (
              <span className="muted small">已选「{presets.find((x) => x.key === preset)?.label}」,输入后发送;再次点击取消。</span>
            )}
          </div>
        );
      })()}

      {/* 选择填空式模板(2026-09-09):点 chip 弹填空;⚙ 管理用户模板 */}
      {fillChip && (
        <TemplateFillDialog
          chip={fillChip}
          busy={!!task}
          onSend={sendFilled}
          onClose={() => setFillChip(null)}
        />
      )}
      {mgrOpen && (
        <TemplateManagerDialog
          templates={userTpls}
          onSave={saveTemplates}
          onClose={() => setMgrOpen(false)}
        />
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
          {/* 批次三①:文件附件(txt/md 两种;读入全文随消息附加,不落盘) */}
          <input type="file" accept=".txt,.md,text/plain" style={{ display: "none" }}
            ref={(el) => { fileInputRef.current = el; }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              f.text().then((txt) => {
                setChips((cur) => [...cur, { type: "file", label: f.name, text: txt }]);
              }).catch(() => setCtxMsg("文件读取失败"));
              e.target.value = "";
            }} />
          <button className="link" title="附件 txt/md:全文随下一条消息发给 AI(超 8K 截断)"
            onClick={() => fileInputRef.current?.click()}>📎 附件</button>
        </div>
      )}
      {pickerOpen && refs && (
        <ChatRefPicker
          refs={refs} pickerTab={pickerTab} setPickerTab={setPickerTab}
          setPickerOpen={setPickerOpen} addChip={addChip} />
      )}

      {(() => {
        const win = contextWindowOf(ctxModel);
        const lastMeta = [...messages].reverse()
          .find((m) => m.role === "assistant" && m.meta?.request_tokens)?.meta;
        const lastReq = lastMeta?.request_tokens;
        if (!win || !lastReq) return null;
        // 批次三③去太极客:常驻极简读数+阈值变色(40/60 与⑤预警线对齐),明细进悬停
        const pct = Math.min(100, (lastReq / win) * 100);
        const tone = pct >= 60 ? "var(--err)" : pct >= 40 ? "#e0af68" : "var(--ok, #9ece6a)";
        const cached = lastMeta?.cached_tokens != null && lastMeta.request_tokens
          ? `缓存命中 ${Math.round((lastMeta.cached_tokens / lastMeta.request_tokens) * 100)}%`
          : "缓存命中 —";
        const detail = `最近一次请求装配 ${lastReq.toLocaleString()} tokens · 窗口 `
          + `${win.toLocaleString()} · ${ctxModel ?? "?"} · ${cached}`;
        return (
          <div className="ctx-gauge muted small"
            style={{ display: "flex", alignItems: "center", gap: 8 }} title={detail}>
            <span style={{ color: tone }}>上下文 {pct.toFixed(1)}%</span>
            <span style={{ flex: 1, height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
              <span style={{ display: "block", height: "100%", width: `${pct}%`, background: tone }} />
            </span>
            {showEng && (
              <span>≈ {lastReq.toLocaleString()} tokens @ {ctxModel} · {cached}</span>
            )}
            <button className="link" title="工程信息常显开关(默认关=大众视图;开着显示模型名/成本/缓存/详细占用)"
              onClick={() => setShowEng((v) => {
                try { localStorage.setItem("chat:showEngineering", v ? "0" : "1"); } catch { /* 忽略 */ }
                return !v;
              })}>{showEng ? "🛠 工程信息:开" : "🛠 工程信息:关"}</button>
            {sid && (
              <button className="link" title="纯算法把更早轮次拼成前情提要(零 LLM,原文全留库);此后装配=提要+最近16条原文,缓存只在压缩点付一次全价"
                onClick={() => {
                  api.compactSession(sid).then((r) => {
                    setCtxMsg(r.message);
                    setTimeout(() => setCtxMsg(""), 4000);
                    loadMessages?.();
                  }).catch((e) => setCtxMsg(`压缩失败:${String((e as Error).message || e)}`));
                }}>🧹 压缩本线</button>
            )}
            {ctxMsg && <span className="small" style={{ color: "var(--ok, #9ece6a)" }}>{ctxMsg}</span>}
          </div>
        );
      })()}
      <div className="row">
        <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // 体感三桶 2026-09-05:回车直接发送(Shift+Enter 换行),与发送按钮同禁用态
            if (e.key === "Enter" && !e.shiftKey && !task && input.trim()) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={allowRefs
            ? "对审稿主编说点什么;@引用 可附加章/角色/条目/伏笔上下文(回车发送,Shift+回车换行)"
            : "对模型说点什么…(回车发送,Shift+回车换行)"} />
        <button className="primary" onClick={() => send()} disabled={!!task || !input.trim()}>
          {task ? "生成中…" : "发送"}
        </button>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
