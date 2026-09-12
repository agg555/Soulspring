import { useEffect, useState } from "react";
import { api } from "../api";
import type { ChatRefs, TimelineEvent } from "../types";

/**
 * 复习卡(候选清单落地批 B,2026-09-10):时间线事件速览 + 伏笔计划表。
 * 纯读组合:timelineEvents + chatRefs(伏笔=hook 板 style 状态)两 API,
 * 零新后端;写操作仍回各自原面板(时间线/图谱中心)。
 */
const HOOK_STATUS_CLASS: Record<string, string> = {
  埋设: "badge", 强化: "badge warn", 回收: "badge ok", 闭环: "badge ok",
};

export default function ReviewCardPanel({ pid }: { pid: string }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [refs, setRefs] = useState<ChatRefs | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.timelineEvents(pid).then((r) => setEvents(r.events)).catch(
      (e) => setError(String((e as Error).message || e)));
    api.chatRefs(pid).then(setRefs).catch(() => setRefs(null));
  }, [pid]);

  const hooks = refs?.hooks ?? [];
  const openHooks = hooks.filter((h) => h.status !== "回收" && h.status !== "闭环");

  return (
    <div>
      {error && <p className="error">{error}</p>}

      <h3>🗒 剧情时间线速览({(events ?? []).length})</h3>
      {!events && <p className="muted small">加载中…</p>}
      {events?.length === 0 && <p className="muted small">还没有剧情事件(剧情时间线页签可建)。</p>}
      <ul className="entry-list">
        {(events ?? []).map((e) => (
          <li key={e.id} className="entry">
            <div className="entry-head">
              <b>{e.title}</b>
              <span className={e.status === "已定" ? "badge ok" : "badge"}>{e.status}</span>
              <span className="badge">{e.line}</span>
            </div>
            <p className="muted small" style={{ margin: "2px 0 0" }}>
              {e.time_label || "(无时间标签)"}{e.summary ? ` · ${e.summary.slice(0, 60)}` : ""}
            </p>
          </li>
        ))}
      </ul>

      <h3>🪝 伏笔计划表({hooks.length} 条,未回收 {openHooks.length})</h3>
      {hooks.length === 0 && <p className="muted small">伏笔池为空(图谱中心·伏笔流转板可建)。</p>}
      {hooks.length > 0 && (
        <table className="table" style={{ fontSize: 12 }}>
          <thead>
            <tr><th style={{ textAlign: "left" }}>伏笔</th><th>埋设章</th><th>状态</th></tr>
          </thead>
          <tbody>
            {hooks.map((h, i) => (
              <tr key={i}>
                <td>{h.detail.slice(0, 80)}{h.detail.length > 80 ? "…" : ""}</td>
                <td style={{ textAlign: "center" }}>{h.planted_chapter ?? "—"}</td>
                <td style={{ textAlign: "center" }}>
                  <span className={HOOK_STATUS_CLASS[h.status] ?? "badge"}>{h.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">
        复习口径:写新章前扫一遍——事件推进到哪、哪些伏笔该收了。修改请去
        剧情时间线 / 图谱中心对应板。
      </p>
    </div>
  );
}
