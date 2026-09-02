import { useEffect, useState } from "react";
import { api } from "../api";
import type { Suggestion, TimelineEvent } from "../types";
import ChatPanel from "../components/ChatPanel";

/**
 * 剧情时间线(第三批 C + E,任务词 2026-09-01):
 * - 故事内容视角的事件卡(与 B2 单章生产时间线不混装,本页独立页签);
 * - 时间轴竖排视图 / 卡片列表视图(同一数据);过滤:全部/主线/支线/已定/未定;
 * - +新增事件(内联表单);事件详情侧栏:人可编辑 + 关联章节选择 + 字段历史;
 * - E:侧栏嵌 ChatPanel(owner_type=timeline_event),预设优化/奇思妙想;
 *   事件字段改法走 event_field 轻档 diff 确认(改前值由本页 getAdoptBefore 提供)。
 */
const FILTERS = ["全部", "主线", "支线", "已定", "未定"] as const;

export default function TimelinePanel({ pid }: { pid: string }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [view, setView] = useState<"axis" | "cards">("axis");
  const [filter, setFilter] = useState<string>("全部");
  const [adding, setAdding] = useState(false);
  const [nf, setNf] = useState({ time_label: "", title: "", summary: "", line: "主线", status: "未定" });
  const [openEvt, setOpenEvt] = useState<TimelineEvent | null>(null);
  const [linkChapterId, setLinkChapterId] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 4000); };

  const load = () => {
    api.timelineEvents(pid).then((r) => {
      setEvents(r.events);
      setOpenEvt((cur) => (cur ? r.events.find((e) => e.id === cur.id) ?? null : null));
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, [pid]);

  const openDetail = async (eid: string) => {
    try {
      const r = await api.timelineEventDetail(eid);
      setOpenEvt(r.event);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  // 轻档采纳的改前值(供 ChatPanel 确认框):优先当前打开的事件,其次列表
  const getAdoptBefore = (s: Suggestion): string => {
    const eid = s.target?.event_id;
    const cur = (openEvt?.id === eid ? openEvt : null) ?? events?.find((e) => e.id === eid);
    if (!cur || !s.target?.field) return "";
    return String((cur as unknown as Record<string, unknown>)[s.target.field] ?? "");
  };

  const createEvent = async () => {
    if (!nf.title.trim()) return;
    setError("");
    try {
      await api.createTimelineEvent(pid, nf);
      setAdding(false);
      setNf({ time_label: "", title: "", summary: "", line: "主线", status: "未定" });
      flash("事件已新增");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const saveField = async (eid: string, patch: Partial<TimelineEvent>) => {
    setError("");
    try {
      await api.updateTimelineEvent(eid, patch);
      flash("已保存");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const removeEvent = async (eid: string) => {
    if (!confirm("删除该事件(关联记录一并清)?")) return;
    try {
      await api.deleteTimelineEvent(eid);
      setOpenEvt(null);
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const linkChapter = async () => {
    if (!openEvt || !linkChapterId) return;
    try {
      await api.linkEventChapter(openEvt.id, linkChapterId);
      setLinkChapterId("");
      load();                 // 列表卡片同步刷新(两视图同数据)
      openDetail(openEvt.id);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const unlinkChapter = async (nid: string) => {
    if (!openEvt) return;
    try {
      await api.unlinkEventChapter(openEvt.id, nid);
      load();
      openDetail(openEvt.id);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const shown = (events ?? []).filter((e) =>
    filter === "全部" ? true : filter === "主线" ? e.line === "主线"
      : filter === "支线" ? e.line === "支线"
      : filter === "已定" ? e.status === "已定" : e.status === "未定");

  if (error && !events) return <p className="error">{error}</p>;
  if (!events) return <p className="muted">加载中…</p>;

  const eventCard = (e: TimelineEvent, i: number) => (
    <div className="entry evt-card" onClick={() => openDetail(e.id)}>
      <div className="entry-head">
        <span className="evt-serial">{i + 1}</span>
        {e.time_label && <span className="badge info">{e.time_label}</span>}
        <b>{e.title}</b>
        <span className={`badge ${e.line === "主线" ? "info" : ""}`}>{e.line}</span>
        <span className={`badge ${e.status === "已定" ? "ok" : "warn"}`}>{e.status}</span>
      </div>
      {e.summary && <p className="muted small">{e.summary.slice(0, 80)}{e.summary.length > 80 ? "…" : ""}</p>}
      <p className="muted small">
        {e.chapters.length > 0 ? `至章:${e.chapters.map((c) => c.title).join("、")}` : "(未关联章节)"}
      </p>
    </div>
  );

  return (
    <div>
      <div className="row spread">
        <div className="row" style={{ margin: 0 }}>
          <button className={view === "axis" ? "active" : ""} onClick={() => setView("axis")}>时间轴</button>
          <button className={view === "cards" ? "active" : ""} onClick={() => setView("cards")}>卡片列表</button>
          <div className="chips">
            {FILTERS.map((f) => (
              <button key={f} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>{f}</button>
            ))}
          </div>
        </div>
        <button onClick={() => setAdding(!adding)}>+ 新增事件</button>
      </div>
      {adding && (
        <div className="dialog">
          <div className="form">
            <label>时间位置(如"第三个月")<input value={nf.time_label} onChange={(e) => setNf({ ...nf, time_label: e.target.value })} /></label>
            <label>标题 *<input value={nf.title} onChange={(e) => setNf({ ...nf, title: e.target.value })} /></label>
            <label>主线/支线
              <select value={nf.line} onChange={(e) => setNf({ ...nf, line: e.target.value })}>
                <option>主线</option><option>支线</option>
              </select>
            </label>
            <label>状态
              <select value={nf.status} onChange={(e) => setNf({ ...nf, status: e.target.value })}>
                <option>未定</option><option>已定</option>
              </select>
            </label>
            <label className="full">摘要<textarea rows={2} value={nf.summary} onChange={(e) => setNf({ ...nf, summary: e.target.value })} /></label>
          </div>
          <div className="row">
            <button onClick={() => setAdding(false)}>取消</button>
            <button className="primary" onClick={createEvent}>添加</button>
          </div>
        </div>
      )}
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="tl-layout">
        <div className="tl-main">
          {shown.length === 0 && <p className="muted">没有符合条件的事件。点「+ 新增事件」开始铺时间线。</p>}
          {view === "axis" ? (
            <ul className="tl-axis">
              {shown.map((e, i) => (
                <li key={e.id} className="tl-axis-item">
                  <div className="tl-rail">
                    <span className="evt-serial">{i + 1}</span>
                    <span className="tl-line" />
                  </div>
                  {eventCard(e, i)}
                </li>
              ))}
            </ul>
          ) : (
            <div className="entry-list">
              {shown.map((e, i) => eventCard(e, i))}
            </div>
          )}
        </div>

        {openEvt && (
          <div className="tl-side">
            <div className="row spread">
              <b>事件详情</b>
              <button className="link" onClick={() => setOpenEvt(null)}>关闭 ×</button>
            </div>
            <div className="form">
              <label>事件名
                <input defaultValue={openEvt.title} id="evt-title"
                  onBlur={(e) => e.target.value !== openEvt.title && saveField(openEvt.id, { title: e.target.value })} />
              </label>
              <label>时间位置
                <input defaultValue={openEvt.time_label}
                  onBlur={(e) => e.target.value !== openEvt.time_label && saveField(openEvt.id, { time_label: e.target.value })} />
              </label>
              <label>摘要
                <textarea rows={3} defaultValue={openEvt.summary}
                  onBlur={(e) => e.target.value !== openEvt.summary && saveField(openEvt.id, { summary: e.target.value })} />
              </label>
              <label>主线/支线
                <select value={openEvt.line} onChange={(e) => saveField(openEvt.id, { line: e.target.value as "主线" | "支线" })}>
                  <option>主线</option><option>支线</option>
                </select>
              </label>
              <label>状态
                <select value={openEvt.status} onChange={(e) => saveField(openEvt.id, { status: e.target.value as "已定" | "未定" })}>
                  <option>未定</option><option>已定</option>
                </select>
              </label>
            </div>
            <div className="row">
              <button onClick={() => removeEvent(openEvt.id)}>删除事件</button>
            </div>

            <h3>关联章节({openEvt.chapters.length})</h3>
            <ul className="entry-list">
              {openEvt.chapters.map((c) => (
                <li key={c.id} className="entry entry-head">
                  <b>{c.title}</b>
                  <span className="badge">{c.status_label ?? c.status}</span>
                  <button className="link" onClick={() => unlinkChapter(c.id)}>摘除</button>
                </li>
              ))}
              {openEvt.chapters.length === 0 && <li className="muted small">尚未关联章节。</li>}
            </ul>
            <div className="row">
              <select value={linkChapterId} onChange={(e) => setLinkChapterId(e.target.value)}>
                <option value="">选择要关联的章…</option>
                {(openEvt.all_chapters ?? []).filter((c) => !openEvt.chapters.some((x) => x.id === c.id))
                  .map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
              <button onClick={linkChapter} disabled={!linkChapterId}>关联</button>
            </div>

            {(openEvt.field_history ?? []).length > 0 && (
              <>
                <h3>字段历史</h3>
                {openEvt.field_history!.map((h, i) => (
                  <p key={i} className="small">
                    {h.created_at.replace("T", " ").slice(5, 16)} · {h.field}:
                    「{(h.before || "").slice(0, 20)}」→「{(h.after || "").slice(0, 20)}」
                  </p>
                ))}
              </>
            )}

            <ChatPanel
              projectId={pid}
              ownerType="timeline_event"
              ownerId={openEvt.id}
              defaultSessionName={`事件讨论·${openEvt.title}`}
              allowPresets
              getAdoptBefore={getAdoptBefore}
              onAdopted={() => { openDetail(openEvt.id); load(); }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
