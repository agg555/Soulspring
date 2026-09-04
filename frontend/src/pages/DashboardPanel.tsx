import { useEffect, useState } from "react";
import { api } from "../api";
import { STAGE_LABELS } from "../stages";
import type { DashboardRow, ProductionEvent } from "../types";

/**
 * 书况台(原"驾驶舱",体感三桶 2026-09-04 拍板改名;第三批 B1/B2/B4,执行书原第三批
 * + 任务词 2026-09-01):
 * - B1 每章一行:状态/字数/审计 critical·警告/评审七维/朱雀人工%/累计成本/最近阶段;
 * - B2 点行展开单章生产时间线(装配→草稿→审计→人改→终审,聚合现成日志表);
 * - B4 质量分 = 加权和(critical 一票否决仅展示),权重页内可调、改后重算生效;
 *   只展示留痕,不改任何既有闸门。数值口径与各面板同源(判据:抽 2 章对账一致)。
 */
const KIND_COLOR: Record<string, string> = {
  装配: "#8b93a1", 草稿任务: "#7aa2f7", "AI 自修": "#7aa2f7",
  补丁: "#9ece6a", 状态: "#e0c060", 朱雀: "#f7768e",
};

export default function DashboardPanel({ pid }: { pid: string }) {
  const [data, setData] = useState<import("../types").DashboardData | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [events, setEvents] = useState<ProductionEvent[]>([]);
  const [nodeTitle, setNodeTitle] = useState("");
  const [wErr, setWErr] = useState("");
  const [error, setError] = useState("");

  const load = () => {
    api.dashboard(pid).then(setData).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, [pid]);

  const openTimeline = async (row: DashboardRow) => {
    if (openRow === row.node_id) { setOpenRow(null); return; }
    setOpenRow(row.node_id);
    setEvents([]);
    try {
      const r = await api.productionTimeline(row.node_id, pid);
      setEvents(r.events);
      setNodeTitle(r.node.title);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const setWeight = async (key: "w_review" | "w_zhuque" | "w_cost", v: string) => {
    setWErr("");
    try {
      await api.putDashboardWeights(pid, { [key]: Number(v) || 0 });
      load();
    } catch (e: unknown) {
      setWErr(String((e as Error).message || e));
    }
  };

  if (error && !data) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>全书书况(B1 · 每章一行)</h3>
      <p className="muted small">
        数值与各面板同源聚合;点行展开 B2 单章生产时间线;质量分为展示留痕,不改任何闸门。
      </p>
      <table>
        <thead>
          <tr>
            <th>章</th><th>状态</th><th>字数</th><th>审计</th><th>评审七维</th>
            <th>朱雀人工%</th><th>累计成本</th><th>质量分(B4)</th><th>最近生成阶段</th>
          </tr>
        </thead>
        <tbody>
          {data.chapters.map((r) => (
            <tr key={r.node_id} style={{ cursor: "pointer" }} onClick={() => openTimeline(r)}>
              <td><b>{r.title}</b></td>
              <td><span className={`badge ${r.status === "finalized" ? "ok" : r.status === "unwritten" ? "" : "warn"}`}>{r.status_label}</span></td>
              <td>{r.words || "—"}</td>
              <td>
                {r.critical > 0
                  ? <span className="badge warn">{r.critical} critical</span>
                  : r.warning > 0 ? <span className="badge info">{r.warning} 警告</span>
                  : r.critical + r.warning === 0 && r.last_stage ? <span className="badge ok">通过</span>
                  : "—"}
              </td>
              <td className="small">
                {r.review?.scores
                  ? Object.entries(r.review.scores).map(([k, v]) => `${k} ${v.score}`).join(" · ")
                  : "—"}
              </td>
              <td>{r.zhuque_human == null ? "—" : `${Math.round(r.zhuque_human)}%`}</td>
              <td>¥{r.cost.toFixed(4)}</td>
              <td>
                {r.quality.veto
                  ? <span className="badge warn">critical 一票否决</span>
                  : r.quality.score == null
                    ? "—"
                    : <b>{r.quality.score}</b>}
              </td>
              <td className="muted small">
                {r.last_stage ? `${(STAGE_LABELS as Record<string, string>)[r.last_stage] ?? r.last_stage}` : "—"}
              </td>
            </tr>
          ))}
          {data.chapters.length === 0 && (
            <tr><td colSpan={9} className="muted">还没有章节点。</td></tr>
          )}
        </tbody>
      </table>

      <div className="row" style={{ marginTop: 8 }}>
        <span className="muted small">质量分权重(B4,改后重算生效):</span>
        <label className="muted small">评审×{data.weights.w_review}
          <input className="w-temp" type="number" step="0.1" defaultValue={data.weights.w_review}
            onBlur={(e) => setWeight("w_review", e.target.value)} />
        </label>
        <label className="muted small">朱雀×{data.weights.w_zhuque}
          <input className="w-temp" type="number" step="0.1" defaultValue={data.weights.w_zhuque}
            onBlur={(e) => setWeight("w_zhuque", e.target.value)} />
        </label>
        <label className="muted small">成本×{data.weights.w_cost}
          <input className="w-temp" type="number" step="0.1" defaultValue={data.weights.w_cost}
            onBlur={(e) => setWeight("w_cost", e.target.value)} />
        </label>
        <span className="muted small">(输入后点别处生效;成本分 = 10×(1-成本/¥{data.alert}告警线))</span>
      </div>
      {wErr && <p className="error">{wErr}</p>}

      {openRow && (
        <div className="dialog">
          <div className="row spread">
            <b>B2 单章生产时间线:{nodeTitle}</b>
            <button className="link" onClick={() => setOpenRow(null)}>收起</button>
          </div>
          <p className="muted small">工程调用链(与日志表原始记录同源):装配 → 草稿 → 审计/人改 → 终审。</p>
          <ul className="prod-timeline">
            {events.map((e, i) => (
              <li key={i}>
                <span className="prod-dot" style={{ background: KIND_COLOR[e.kind.split(" ")[0]] ?? "#8b93a1" }} />
                <span className="muted small">{(e.at || "").replace("T", " ").slice(5, 16) || "(早期记录)"}</span>
                <span className="badge">{e.kind}</span>
                <span className="small">{e.detail}</span>
              </li>
            ))}
            {events.length === 0 && <li className="muted small">本章暂无生产日志。</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
