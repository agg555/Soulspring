import { useEffect, useState } from "react";
import { api } from "../api";
import type { Overview, Project, WordStats } from "../types";
import NewBookWizard from "./NewBookWizard";
import BookWorkspace from "./BookWorkspace";

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [words, setWords] = useState<WordStats | null>(null);
  const [error, setError] = useState("");
  const [wizard, setWizard] = useState(false);
  const [openBook, setOpenBook] = useState<string | null>(null);

  const load = () => {
    api.overview().then(setData).catch((e) => setError(String(e.message || e)));
    // 码字总卡(第三批 B3):pid 空 = 全书合计;近 7 日人工趋势
    api.wordStats("").then(setWords).catch(() => {});
  };
  useEffect(load, []);

  if (openBook) {
    return <BookWorkspace pid={openBook} onBack={() => { setOpenBook(null); load(); }} />;
  }

  const weekMax = words ? Math.max(10, ...words.week.map((w) => w.human)) : 10;

  return (
    <div>
      <h2>项目总览</h2>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <div className="cards">
            <div className="card">
              <div className="card-num">{words ? words.today.human : "…"}</div>
              <div className="card-label">今日人工码字(全书籍)</div>
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
              <p className="muted small" style={{ margin: "0 0 6px" }}>
                近 7 日人工码字趋势(今日 {words.today.human} 字 · AI {words.today.ai} 字,分列不混计)
              </p>
              <svg viewBox="0 0 480 70" className="wc-chart" role="img" aria-label="近7日码字趋势">
                {words.week.map((w, i) => {
                  const bw = 52;
                  const x = i * 68 + 8;
                  const hh = (Math.max(w.human, 0) / weekMax) * 44;
                  return (
                    <g key={i}>
                      {w.human > 0 && <rect x={x} y={52 - hh} width={bw} height={hh} fill="#9ece6a" />}
                      <text x={x + bw / 2} y={64} fontSize={9} textAnchor="middle" fill="var(--muted)">{w.day}</text>
                      <text x={x + bw / 2} y={48 - hh} fontSize={9} textAnchor="middle" fill="var(--muted)">
                        {w.human > 0 ? w.human : ""}
                      </text>
                    </g>
                  );
                })}
              </svg>
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
