import { useEffect, useState } from "react";
import { api } from "../api";
import WcBars from "./WcBars";
import type { WordStats } from "../types";

// 码字统计浮窗(二期②自 WorkbenchPanel 拆出,单文件克制红线):右下角可折叠小浮条。
// 人工字数才叫"码字",AI 生成必须分列展示(人主编 99% 的可观测化);数据=word_count_log。
// 含码字计时器(开始/暂停/重置,localStorage 持久切页签不打断)+ 时段人工字数
// (word-stats since)+ 世界时钟(本地+UTC 每秒)+ 24h 分列柱状(共享 WcBars)。
export default function WordFloat({ pid, nid, tick }: { pid: string; nid: string | null; tick: number }) {
  const [s, setS] = useState<WordStats | null>(null);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(new Date());
  // 计时器:running + startedAt(本次开始时刻)+ accMs(此前累计);localStorage 持久
  const [timer, setTimer] = useState<{ running: boolean; startedAt: number; accMs: number }>(() => {
    try {
      const raw = localStorage.getItem("wc_timer");
      if (raw) return JSON.parse(raw);
    } catch { /* 忽略坏数据 */ }
    return { running: false, startedAt: 0, accMs: 0 };
  });

  const persist = (t: typeof timer) => {
    setTimer(t);
    try { localStorage.setItem("wc_timer", JSON.stringify(t)); } catch { /* 忽略 */ }
  };
  const elapsedMs = timer.accMs + (timer.running ? Date.now() - timer.startedAt : 0);
  const timerSince = timer.running || timer.accMs > 0
    ? new Date(timer.running ? timer.startedAt : Date.now() - timer.accMs).toISOString()
    : "";

  const load = () => {
    api.wordStats(pid, nid ?? undefined, timerSince || undefined).then(setS).catch(() => {});
  };
  useEffect(load, [pid, nid, tick, timerSince]);
  // 每秒走字(时钟 + 计时器)
  useEffect(() => {
    const iv = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(iv);
  }, []);
  // 统计轮询 30s
  useEffect(() => {
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, nid, timerSince]);

  const mmss = (ms: number) => {
    const t = Math.floor(ms / 1000);
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
    const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  };

  if (!s) return null;
  const local = now.toLocaleString("sv-SE").slice(0, 16);   // YYYY-MM-DD HH:MM
  const utc = now.toISOString().slice(0, 16).replace("T", " ");
  return (
    <div className="wc-float">
      {!open ? (
        <button className="wc-bar" onClick={() => setOpen(true)}
          title="码字统计 + 专注计时(人工/AI 分列)">
          今日人工 {s.today.human} 字 · 本小时 {s.hour.human} 字 · 本章 {s.chapter.human} 字
          {" · "}⏱ {mmss(elapsedMs)}{timer.running ? "" : " (停)"}
          {" ▲"}
        </button>
      ) : (
        <div className="wc-panel">
          <div className="row spread">
            <b>码字统计与专注计时</b>
            <button className="link" onClick={() => setOpen(false)}>收起 ▼</button>
          </div>
          <p className="small">
            今日:人工 <b>{s.today.human}</b> 字 / AI {s.today.ai} 字 ·
            本小时人工 {s.hour.human} 字 · 本章人工 {s.chapter.human} 字
          </p>
          <div className="row" style={{ alignItems: "center" }}>
            <span className="badge info" style={{ fontSize: 14 }}>⏱ {mmss(elapsedMs)}</span>
            <span className="small">时段人工 <b>{s.since.human ?? 0}</b> 字</span>
            {!timer.running ? (
              <button onClick={() => persist({ running: true, startedAt: Date.now(), accMs: timer.accMs })}>
                {timer.accMs > 0 ? "继续" : "开始"}
              </button>
            ) : (
              <button onClick={() => persist({
                running: false, startedAt: timer.startedAt,
                accMs: timer.accMs + (Date.now() - timer.startedAt),
              })}>暂停</button>
            )}
            <button onClick={() => persist({ running: false, startedAt: 0, accMs: 0 })}>重置</button>
          </div>
          <p className="muted small">世界时钟:本地 {local} · UTC {utc}</p>
          <p className="muted small">近 24 小时(绿=人工码字,蓝=AI 生成,分列不混计;虚线=昨/今分界):</p>
          <WcBars height={112}
            buckets={s.last24h.map((b) => ({ label: b.hour, human: b.human, ai: b.ai, aiMs: b.ai_ms }))}
            nowLast sep={{ index: Math.max(0, s.last24h.findIndex((b) => b.hour === "00:00")) }} />
        </div>
      )}
    </div>
  );
}
