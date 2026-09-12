import { useEffect, useState } from "react";
import { api } from "../api";
import type { Overview, Project, WordStats } from "../types";
import NewBookWizard from "./NewBookWizard";
import BookWorkspace from "./BookWorkspace";
import WcBars from "../components/WcBars";

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [words, setWords] = useState<WordStats | null>(null);
  const [error, setError] = useState("");
  const [wizard, setWizard] = useState(false);
  const [openBook, setOpenBook] = useState<string | null>(null);
  // 批次七⑩:统计细化——粒度日/时切换 + 今日实时(30s 轻刷新,写作中途回总览即见新数)
  const [gran, setGran] = useState<"day" | "hour">("day");

  const load = () => {
    api.overview().then(setData).catch((e) => setError(String(e.message || e)));
    // 码字总卡(第三批 B3):pid 空 = 全书合计;近 7 日人工趋势
    api.wordStats("").then(setWords).catch(() => {});
  };
  useEffect(load, []);
  useEffect(() => {
    const iv = setInterval(() => api.wordStats("").then(setWords).catch(() => {}), 30000);
    return () => clearInterval(iv);
  }, []);

  if (openBook) {
    return <BookWorkspace pid={openBook} onBack={() => { setOpenBook(null); load(); }} />;
  }

  // 批次七⑩:AI/人工分列柱状(分列不混计);二期②改共享 WcBars(槽位中心对齐/
  // 末桶「现在」/昨今分隔/悬浮提示框带 AI 用时)
  const series = words ? (gran === "day"
    ? words.week.map((w) => ({ label: w.day, human: w.human, ai: w.ai, aiMs: w.ai_ms }))
    : (words.last24h ?? []).map((w) => ({
        label: w.hour, human: w.human, ai: w.ai, aiMs: w.ai_ms,
      }))) : [];

  return (
    <div>
      <h2>项目总览</h2>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <div className="cards">
            <div className="card">
              <div className="card-num">{words ? words.today.human : "…"}</div>
              <div className="card-label">今日人工码字(全书籍 · 30s 实时)</div>
            </div>
            <div className="card">
              <div className="card-num">{words ? words.today.ai : "…"}</div>
              <div className="card-label">今日 AI 字数(分列不混计)</div>
            </div>
            <div className="card">
              <div className="card-num">¥{data.today_cost.toFixed(4)}</div>
              <div className="card-label">今日成本</div>
            </div>
            <div className="card">
              <div className="card-num">¥{data.month_cost.toFixed(4)}</div>
              <div className="card-label">本月累计</div>
            </div>
            <div className="card">
              <div className="card-num">{data.today_calls}</div>
              <div className="card-label">今日调用次数</div>
            </div>
          </div>

          {words && (
            <div className="card">
              <p className="muted small" style={{ margin: "0 0 6px", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span>
                  {gran === "day" ? "近 7 日" : "近 24 小时"}码字(今日人工 {words.today.human} · AI {words.today.ai} 字,分列不混计)
                </span>
                <span className="badge">
                  本图合计 {series.reduce((acc, x) => acc + x.human + x.ai, 0)} 字
                </span>
                {words.total && (
                  <span className="badge info" title="全部书记录的净字数(人工+AI,删改已扣减)">
                    总字数 人工 {words.total.human} · AI {words.total.ai}
                    · 合计 {words.total.human + words.total.ai} 字
                  </span>
                )}
                <span style={{ marginLeft: "auto" }}>
                  <button className={gran === "day" ? "active" : ""} onClick={() => setGran("day")}>日</button>
                  <button className={gran === "hour" ? "active" : ""} onClick={() => setGran("hour")}>时</button>
                </span>
              </p>
              <WcBars
                buckets={series.map((s, i) =>
                  gran === "day" && i === series.length - 1 ? { ...s, label: "今天" } : s)}
                nowLast={gran === "hour"}
                sep={gran === "day" ? { index: Math.max(0, series.length - 1) }
                  : { index: Math.max(0, series.findIndex((s) => s.label === "00:00")) }}
              />
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                <span style={{ color: "#9ece6a" }}>■</span> 人工 <span style={{ color: "#7aa2f7", marginLeft: 8 }}>■</span> AI(悬浮柱看当日明细与 AI 用时;虚线=昨/今分界)
              </p>
            </div>
          )}

          <h3>书架</h3>
          {data.projects.length === 0 && <p className="muted">还没有书。点「+ 新建书」走 F0 向导。</p>}
          <ul className="project-list">
            {data.projects.map((p: Project) => (
              <li key={p.id} className="book-row">
                <button className="link" onClick={() => setOpenBook(p.id)}>
                  <b>{p.name}</b>
                </button>
                {p.genre && <span className="muted"> · {p.genre}</span>}
                {p.description && <span className="muted"> — {p.description}</span>}
              </li>
            ))}
          </ul>

          {wizard ? (
            <NewBookWizard
              onDone={(pid) => { setWizard(false); load(); setOpenBook(pid); }}
              onCancel={() => setWizard(false)}
            />
          ) : (
            <button className="primary" onClick={() => setWizard(true)}>+ 新建书(F0 向导)</button>
          )}
        </>
      )}
    </div>
  );
}
