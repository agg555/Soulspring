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
const PAGE_SIZE = 100;   // 二期①五面审计:千章书 1034 行全量渲染太重,分页 100/页

export default function DashboardPanel({ pid, onGoPanel }: {
  pid: string;
  onGoPanel?: (tab: "workbench" | "review", nodeId: string) => void;   // 批次二:低分章一键跳
}) {
  const [data, setData] = useState<import("../types").DashboardData | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [events, setEvents] = useState<ProductionEvent[]>([]);
  const [nodeTitle, setNodeTitle] = useState("");
  const [wErr, setWErr] = useState("");
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);

  const load = () => {
    api.dashboard(pid).then(setData).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, [pid]);
  useEffect(() => setPage(0), [pid]);   // 换书回第一页

  const chapters = data?.chapters ?? [];
  const pageCount = Math.max(1, Math.ceil(chapters.length / PAGE_SIZE));
  const pageRows = chapters.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

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
      <h3 style={{ marginTop: 0 }}>全书书况(每章一行)</h3>
      <p className="muted small">
        数值与各面板同源聚合;点行展开 B2 单章生产时间线;质量分为展示留痕,不改任何闸门。
      </p>
      {/* 节奏谱(候选清单落地批 B):全章字数折线,点按状态着色;零 LLM 纯展示 */}
      {chapters.length > 1 && (() => {
        const W = 480, H = 90, pad = 6;
        const ordered = [...chapters].reverse();   // 创建序(第一卷/第一章在左)
        const maxW = Math.max(1000, ...ordered.map((r) => r.words || 0));
        const px = (i: number) => pad + (i / Math.max(1, ordered.length - 1)) * (W - pad * 2);
        const py = (w: number) => H - 14 - ((w || 0) / maxW) * (H - 24);
        const pts = ordered.map((r, i) => `${px(i)},${py(r.words)}`).join(" ");
        return (
          <div style={{ marginBottom: 8 }}>
            <p className="muted small" style={{ margin: "0 0 2px" }}>
              节奏谱:{ordered.length} 章字数走势(峰值 {maxW} 字);左=第 1 章。
            </p>
            <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="章节字数节奏谱">
              <line x1={pad} y1={H - 14} x2={W - pad} y2={H - 14} stroke="var(--border)" />
              <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth={1.6} />
              {ordered.map((r, i) => (
                <circle key={r.node_id} cx={px(i)} cy={py(r.words)} r={
                  r.status === "finalized" ? 3 : 2
                } fill={r.status === "finalized" ? "#9ece6a"
                  : r.status === "final_review" ? "#bb9af7"
                    : r.status === "unwritten" ? "var(--muted)" : "#e0af68"}>
                  <title>{`${r.title}:${r.words} 字(${r.status_label})`}</title>
                </circle>
              ))}
            </svg>
          </div>
        );
      })()}

      {/* 人物戏份曲线(候选清单落地批 A):同框边 at_chapter 聚合,散点带 */}
      <ScreenTimeBand pid={pid} />
      {chapters.length > PAGE_SIZE && (
        <div className="row" style={{ margin: "4px 0" }}>
          <button className="link" disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}>← 上一页</button>
          <span className="muted small">第 {page + 1}/{pageCount} 页
            · 共 {chapters.length} 章(每页 {PAGE_SIZE})</span>
          <button className="link" disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => p + 1)}>下一页 →</button>
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>章</th><th>状态</th><th>字数</th><th>审计</th><th>评审七维</th>
            <th>朱雀人工%</th><th>累计成本</th><th>质量分</th><th>最近生成阶段</th>
            <th>去</th>
          </tr>
        </thead>
        <tbody>
          {pageRows.map((r) => (
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
              <td onClick={(e) => e.stopPropagation()}>
                {onGoPanel && r.status !== "unwritten" && (
                  <span className="row" style={{ margin: 0, gap: 2 }}>
                    <button className="link" title="去写章工作台"
                      onClick={() => onGoPanel("workbench", r.node_id)}>改</button>
                    <button className="link" title="去终审对话台"
                      onClick={() => onGoPanel("review", r.node_id)}>审</button>
                  </span>
                )}
              </td>
            </tr>
          ))}
          {data.chapters.length === 0 && (
            <tr><td colSpan={9} className="muted">还没有章节点。</td></tr>
          )}
        </tbody>
      </table>

      <div className="row" style={{ marginTop: 8 }}>
        <span className="muted small">质量分权重(改后即时生效):</span>
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

/**
 * 人物戏份曲线(候选清单落地批 A):同框边 at_chapter 聚合散点带——
 * 每角色一行,X=章号,点=该章有同框出场;按出场次数降序。纯统计零 LLM。
 */
function ScreenTimeBand({ pid }: { pid: string }) {
  const [roles, setRoles] = useState<{ name: string; chapter_nos: number[]; count: number }[] | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    api.screenTime(pid).then((r) => setRoles(r.roles)).catch(() => setRoles([]));
  }, [pid]);
  if (roles === null || roles.length === 0) return null;
  const maxNo = Math.max(...roles.flatMap((r) => r.chapter_nos));
  const rowH = 18;
  const H = roles.length * rowH + 22;
  const visibleH = open ? H : rowH * 3 + 22;
  return (
    <div style={{ marginBottom: 8 }}>
      <p className="muted small" style={{ margin: "0 0 2px", display: "flex" }}>
        <span>戏份曲线:{roles.length} 位人物(按同框出场;可展开)</span>
        <button className="link" style={{ marginLeft: "auto" }}
          onClick={() => setOpen(!open)}>{open ? "收起" : "展开全部"}</button>
      </p>
      <svg viewBox={`0 0 480 ${visibleH}`} width="100%" role="img" aria-label="人物戏份散点带">
        <line x1={40} y1={visibleH - 14} x2={476} y2={visibleH - 14} stroke="var(--border)" />
        {(open ? roles : roles.slice(0, 3)).map((r, i) => (
          <g key={r.name}>
            <text x={2} y={i * rowH + 12} fontSize={10}
              fill="var(--text)">{r.name.slice(0, 5)}</text>
            {r.chapter_nos.map((no) => (
              <circle key={no} cx={40 + ((no - 1) / Math.max(1, maxNo)) * 436}
                cy={i * rowH + 8} r={3} fill="var(--accent)" opacity={0.85}>
                <title>{`${r.name} · 第${no}章同框(共 ${r.count} 章)`}</title>
              </circle>
            ))}
          </g>
        ))}
        {!open && roles.length > 3 && (
          <text x={400} y={2 * rowH + 8} fontSize={10}
            fill="var(--muted)">…共 {roles.length} 人</text>
        )}
      </svg>
    </div>
  );
}
