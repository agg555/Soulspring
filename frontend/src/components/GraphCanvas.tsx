import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { GraphEdge, GraphNode, Suggestion } from "../types";
import ChatPanel from "./ChatPanel";
import { uiConfirm, uiPrompt } from "./uiConfirm";

/**
 * 统一图谱引擎(第四批 A,任务词 2026-09-01):
 * - 方框节点(圆角卡片:label + 可选 sub_label);连线 = 边缘锚点间曲线,类别色+标签;
 * - 画布交互:空白拖动平移 / 滚轮缩放 / 节点拖动(位置落库持久化);
 * - 网格吸附(20px,板级开关);拖动靠近其他节点边缘锚点热区高亮,松手自动建边;
 * - 边中点控制点:加派生节点 / 改标签 / 改类别 / 删除;同一对节点允许多条线;
 * - 自研薄实现(pointer events + state;开源参考按任务词口径:成熟算法自研即可);
 * - 侧栏:节点/边详情(人可改)+ ChatPanel(graph_node/graph_edge),板级对话(graph_board);
 *   AI 改动走 graph_field 轻档 / graph_add 批准闸门,无直改。
 */
const NODE_W = 128, NODE_H = 48, GRID = 20;
const KIND_COLOR: Record<string, string> = {
  亲情: "#e0af68", 爱情: "#f7768e", 友情: "#9ece6a", 敌对: "#bb9af7", 其他: "#7aa2f7",
  因果: "#7aa2f7", 并行: "#9ece6a", 承接: "#e0af68", 持有: "#e0af68", 来源: "#9ece6a",
  去向: "#7aa2f7", 相邻: "#9ece6a", 通道: "#e0af68", 从属: "#bb9af7", 同盟: "#9ece6a",
  衍生: "#7aa2f7", 克制: "#f7768e", 自由: "#8b93a1",
};
const EDGE_KINDS = Object.keys(KIND_COLOR);

/* 节点实体类型着色(体感三桶 2026-09-04 拍板 3a):l1 六类+事件/自由;色板沿用边类别同族 */
const NODE_CATEGORY_COLOR: Record<string, string> = {
  worldview: "#7aa2f7", character: "#9ece6a", power: "#bb9af7", faction: "#e0af68",
  map: "#4fd6be", item_economy: "#ff9e64", timeline_event: "#f7768e", free: "#8b93a1",
};
const NODE_CATEGORY_LABEL: Record<string, string> = {
  worldview: "世界观", character: "角色", power: "力量", faction: "势力",
  map: "地理", item_economy: "物品经济", timeline_event: "事件", free: "自由",
};

type Pt = { x: number; y: number };

/* 顺手修(体感三桶 2026-09-04):定宽框内换行/截断,防长标签溢出压到邻居 */
const CHAR_W = (ch: string) => (ch.charCodeAt(0) > 0xff ? 13 : 7.5);

/** 定宽内换行,最多 maxLines 行;最后一行放不下以省略号收尾。 */
export function wrapText(text: string, maxW: number, maxLines: number): string[] {
  const chars = Array.from(text);
  const lines: string[] = [];
  let cur: string[] = [], curW = 0;
  for (const ch of chars) {
    const w = CHAR_W(ch);
    if (curW + w > maxW && cur.length) {
      if (lines.length === maxLines - 1) {
        while (curW + CHAR_W("…") > maxW && cur.length > 1) {
          curW -= CHAR_W(cur.pop()!);
        }
        return [...lines, cur.join("") + "…"];
      }
      lines.push(cur.join(""));
      cur = []; curW = 0;
    }
    cur.push(ch); curW += w;
  }
  if (cur.length) lines.push(cur.join(""));
  return lines;
}

/** 单行截断,超宽以省略号收尾(边标签用)。 */
export function truncText(text: string, maxW: number): string {
  const chars = Array.from(text);
  let total = 0;
  for (const ch of chars) total += CHAR_W(ch);
  if (total <= maxW) return text;
  let curW = 0;
  for (let i = 0; i < chars.length; i++) {
    if (curW + CHAR_W(chars[i]) + CHAR_W("…") > maxW) return chars.slice(0, i).join("") + "…";
    curW += CHAR_W(chars[i]);
  }
  return text;
}

/** 节点中心 a 朝 b 方向与 a 矩形边框的交点(边缘锚点)。 */
function rectAnchor(a: Pt, b: Pt): Pt {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (dx === 0 && dy === 0) return a;
  const sx = dx !== 0 ? (NODE_W / 2) / Math.abs(dx) : Infinity;
  const sy = dy !== 0 ? (NODE_H / 2) / Math.abs(dy) : Infinity;
  const s = Math.min(sx, sy);
  return { x: a.x + dx * s, y: a.y + dy * s };
}

/** 四边中点锚点(自动连线热区)。 */
function sideAnchors(n: GraphNode): { side: string; pt: Pt }[] {
  return [
    { side: "上", pt: { x: n.x, y: n.y - NODE_H / 2 } },
    { side: "下", pt: { x: n.x, y: n.y + NODE_H / 2 } },
    { side: "左", pt: { x: n.x - NODE_W / 2, y: n.y } },
    { side: "右", pt: { x: n.x + NODE_W / 2, y: n.y } },
  ];
}

export default function GraphBoardView({ boardId, onBack, onShowLinks }: {
  boardId: string;
  onBack: () => void;
  onShowLinks?: (etype: string, nid: string, title: string) => void;   // B3 互链
}) {
  const [board, setBoard] = useState<import("../types").GraphBoard | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [pan, setPan] = useState<Pt>({ x: 20, y: 10 });
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<{ type: "node" | "edge"; id: string } | null>(null);
  const [showBoardChat, setShowBoardChat] = useState(false);
  const [edgeMenu, setEdgeMenu] = useState<{ eid: string; sx: number; sy: number } | null>(null);
  const [linkForm, setLinkForm] = useState<{ from: string; to: string } | null>(null);
  const [linkLabel, setLinkLabel] = useState("");
  const [linkKind, setLinkKind] = useState("自由");
  const [genCat, setGenCat] = useState("");
  const [nodeLabel, setNodeLabel] = useState("");
  const [kindOff, setKindOff] = useState<string[]>([]);   // 图例过滤(沿用第三批)
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const svgRef = useRef<SVGSVGElement | null>(null);
  // 拖拽/平移运行态(ref 存,避免重渲染抖动)
  const drag = useRef<{ nid: string; off: Pt } | null>(null);
  const panRef = useRef<{ sx: number; sy: number; pan: Pt } | null>(null);
  const hot = useRef<string | null>(null);
  const [hotNode, setHotNode] = useState<string | null>(null);   // 渲染高亮

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 3500); };

  const load = () => {
    api.graphBoard(boardId).then((r) => {
      setBoard(r.board);
      setNodes(r.nodes);
      setEdges(r.edges);
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, [boardId]);

  const nodeById = (id: string) => nodes.find((n) => n.id === id);

  const toGraph = (clientX: number, clientY: number): Pt => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: (clientX - rect.left - pan.x) / zoom, y: (clientY - rect.top - pan.y) / zoom };
  };
  const toScreen = (gp: Pt): Pt => ({ x: gp.x * zoom + pan.x, y: gp.y * zoom + pan.y });

  // ── 指针交互 ──
  const onNodeDown = (e: React.PointerEvent, n: GraphNode) => {
    if (e.button !== 0) { e.preventDefault(); return; } // 仅左键拖节点(速赢④:中键 autoscroll 曾致画布飞走)
    e.stopPropagation();
    setSelected({ type: "node", id: n.id });
    setEdgeMenu(null);
    const gp = toGraph(e.clientX, e.clientY);
    drag.current = { nid: n.id, off: { x: gp.x - n.x, y: gp.y - n.y } };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  const onCanvasDown = (e: React.PointerEvent) => {
    if (e.button !== 0) { e.preventDefault(); return; } // 仅左键平移;中键默认 autoscroll 会劫持坐标(速赢④)
    setSelected(null);
    setEdgeMenu(null);
    panRef.current = { sx: e.clientX, sy: e.clientY, pan: { ...pan } };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  const onMove = (e: React.PointerEvent) => {
    if (drag.current) {
      const gp = toGraph(e.clientX, e.clientY);
      const n = nodeById(drag.current.nid);
      if (!n) return;
      let nx = gp.x - drag.current.off.x;
      let ny = gp.y - drag.current.off.y;
      if (board?.grid_on) {
        nx = Math.round(nx / GRID) * GRID;
        ny = Math.round(ny / GRID) * GRID;
      }
      setNodes((cur) => cur.map((x) => (x.id === n.id ? { ...x, x: nx, y: ny } : x)));
      // 锚点热区检测(其他节点四边中点,距离 30 内)
      let hit: string | null = null;
      for (const other of nodes) {
        if (other.id === n.id) continue;
        for (const a of sideAnchors(other)) {
          if (Math.hypot(a.pt.x - nx, a.pt.y - ny) < 30) { hit = other.id; break; }
        }
        if (hit) break;
      }
      hot.current = hit;
      setHotNode(hit);
    } else if (panRef.current) {
      setPan({
        x: panRef.current.pan.x + (e.clientX - panRef.current.sx),
        y: panRef.current.pan.y + (e.clientY - panRef.current.sy),
      });
    }
  };

  const onUp = async () => {
    if (drag.current) {
      const n = nodeById(drag.current.nid);
      const target = hot.current;
      drag.current = null;
      hot.current = null;
      setHotNode(null);
      if (n) {
        if (target && target !== n.id) {
          setLinkForm({ from: n.id, to: target });   // A4:松手自动建边 → 小表单
        } else {
          // S6:落格持久化失败不再静默,沿用组件 error 行内提示
          await api.patchGraphNode(n.id, { x: n.x, y: n.y })
            .catch((e: unknown) => setError(`位置保存失败:${String((e as Error).message || e)}`));
        }
      }
    }
    panRef.current = null;
  };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const nz = Math.max(0.4, Math.min(2.5, zoom * factor));
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    setPan({ x: mx - (mx - pan.x) * (nz / zoom), y: my - (my - pan.y) * (nz / zoom) });
    setZoom(nz);
  };

  // 速赢 2.2(2026-09-03):按钮缩放——以画布中心为锚,步进 1.25;重置回 1:1。
  const zoomBy = (factor: number) => {
    const nz = Math.max(0.4, Math.min(2.5, zoom * factor));
    const rect = svgRef.current?.getBoundingClientRect();
    const mx = rect ? rect.width / 2 : 300, my = rect ? rect.height / 2 : 260;
    setPan({ x: mx - (mx - pan.x) * (nz / zoom), y: my - (my - pan.y) * (nz / zoom) });
    setZoom(nz);
  };
  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

  // ── 落库操作 ──
  const confirmLink = async () => {
    if (!linkForm) return;
    try {
      await api.createGraphEdge(boardId, {
        from_node_id: linkForm.from, to_node_id: linkForm.to,
        label: linkLabel.trim(), kind: linkKind,
      });
      setLinkForm(null);
      setLinkLabel("");
      flash("已连线");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const addFreeNode = async () => {
    if (!nodeLabel.trim()) return;
    try {
      // 放到当前视口中心(世界坐标)
      const rect = svgRef.current?.getBoundingClientRect();
      const cx = rect ? (rect.width / 2 - pan.x) / zoom : 200;
      const cy = rect ? (rect.height / 2 - pan.y) / zoom : 200;
      await api.createGraphNode(boardId, {
        label: nodeLabel.trim(), ref_type: "free",
        x: Math.round(cx / GRID) * GRID, y: Math.round(cy / GRID) * GRID,
      });
      setNodeLabel("");
      flash("节点已加");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const generate = async (source: string, category?: string) => {
    try {
      const r = await api.generateGraphNodes(boardId, { source, category });
      flash(`已生成 ${r.created} 个节点${r.skipped ? `(跳过重复 ${r.skipped})` : ""}`);
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };


  // 速赢 2.1(2026-09-03):采纳图谱建议时注入落位锚——edge 用两端中点,节点用其坐标,
  // 其余(纯文本建议)用当前视口中心;后端据此环绕找不重叠空位。
  const getAdoptAnchor = (sug: Suggestion): { x: number; y: number } | null => {
    const t = (sug.target ?? {}) as { edge_id?: string; source_node_id?: string; node_id?: string };
    if (t.edge_id) {
      const e = edges.find((x) => x.id === t.edge_id);
      const a = e && nodeById(e.from_node_id), b = e && nodeById(e.to_node_id);
      if (a && b) return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    }
    const nid = t.source_node_id ?? t.node_id;
    if (nid) {
      const n = nodeById(nid);
      if (n) return { x: n.x, y: n.y };
    }
    return null;
  };

  const addDerived = async (eid: string) => {
    const e = edges.find((x) => x.id === eid);
    const a = e && nodeById(e.from_node_id), b = e && nodeById(e.to_node_id);
    if (!e || !a || !b) return;
    try {
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 + 90 };
      const nn = await api.createGraphNode(boardId, {
        label: "派生节点", ref_type: "free",
        x: Math.round(mid.x / GRID) * GRID, y: Math.round(mid.y / GRID) * GRID,
      });
      await api.createGraphEdge(boardId, {
        from_node_id: e.from_node_id, to_node_id: nn.node.id,
        label: e.label, kind: e.kind,
      });
      setEdgeMenu(null);
      flash("已派生节点并连线");
      load();
    } catch (e2: unknown) {
      setError(String((e2 as Error).message || e2));
    }
  };

  // 轻档采纳改前值(节点/边字段)
  const getAdoptBefore = (s: Suggestion): string => {
    const t = s.target ?? {};
    if (t.node_id) {
      const n = nodes.find((x) => x.id === t.node_id);
      return n ? String((n as unknown as Record<string, unknown>)[t.field ?? ""] ?? "") : "";
    }
    if (t.edge_id) {
      const e = edges.find((x) => x.id === t.edge_id);
      return e ? String((e as unknown as Record<string, unknown>)[t.field ?? ""] ?? "") : "";
    }
    return "";
  };

  const selNode = selected?.type === "node" ? nodeById(selected.id) : null;
  const selEdge = selected?.type === "edge" ? edges.find((x) => x.id === selected.id) : null;
  const edgeMenuEdge = edgeMenu ? edges.find((x) => x.id === edgeMenu.eid) : null;

  // 同对节点多线偏移(A6):按出现序给法向偏移
  const edgeOffset = (eid: string) => {
    const e = edges.find((x) => x.id === eid)!;
    const same = edges.filter((x) =>
      (x.from_node_id === e.from_node_id && x.to_node_id === e.to_node_id) ||
      (x.from_node_id === e.to_node_id && x.to_node_id === e.from_node_id));
    const idx = same.findIndex((x) => x.id === eid);
    return (idx - (same.length - 1) / 2) * 34;
  };

  return (
    <div>
      <div className="row spread">
        <div className="row" style={{ margin: 0 }}>
          <button className="link" onClick={onBack}>← 图谱中心</button>
          <b>{board?.name}</b>
          <label className="row" style={{ margin: 0 }}>
            <input type="checkbox" checked={!!board?.grid_on}
              onChange={async (e) => {
                if (!board) return;
                try {
                  const r = await api.patchGraphBoard(board.id, { grid_on: e.target.checked ? 1 : 0 });
                  setBoard(r.board);
                } catch (er: unknown) {
                  setError(String((er as Error).message || er));
                }
              }} />
            网格
          </label>
        </div>
        <button className="link" onClick={() => setShowBoardChat(!showBoardChat)}>
          {showBoardChat ? "收起板级对话" : "整板 AI 对话"}
        </button>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="row" style={{ flexWrap: "wrap" }}>
        <input placeholder="自由节点名" value={nodeLabel}
          onChange={(e) => setNodeLabel(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") addFreeNode(); }} />
        <button onClick={addFreeNode} disabled={!nodeLabel.trim()}>+ 自由节点</button>
        {board?.kind === "item" || board?.kind === "map" || board?.kind === "faction"
          || board?.kind === "character" || board?.kind === "power" || board?.kind === "worldview" ? (
          <>
            <select value={genCat} onChange={(e) => setGenCat(e.target.value)}>
              <option value="">从档案生成(L1 类别)…</option>
              {(board.kind === "item" ? [["item_economy", "物品经济"]] :
                board.kind === "map" ? [["map", "地图"]] :
                board.kind === "faction" ? [["faction", "势力阵营"]] :
                board.kind === "character" ? [["character", "角色"]] :
                board.kind === "power" ? [["power", "力量体系"]] :
                [["worldview", "世界观"]]).map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </select>
            <button onClick={() => generate("l1_entry", genCat)} disabled={!genCat}>生成节点</button>
          </>
        ) : board?.kind === "event" ? (
          <button onClick={() => generate("timeline_event")}>从时间线生成事件节点</button>
        ) : null}
        <span className="muted small">
          空白拖动=平移 · 滚轮=缩放 · 拖节点落格,靠近锚点松手自动连线 · 点连线中点弹菜单
        </span>
      </div>
      <div className="chips" style={{ marginBottom: 6 }}>
        <span className="muted small">图例过滤:</span>
        {[...new Set(edges.map((e) => e.kind))].map((k) => (
          <button key={k} className={`chip ${kindOff.includes(k) ? "" : "on"}`}
            onClick={() => setKindOff((cur) =>
              cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k])}>
            <span style={{ color: kindOff.includes(k) ? "inherit" : KIND_COLOR[k] ?? "inherit" }}>●</span> {k}
          </button>
        ))}
      </div>
      {/* 节点实体类型图例(拍板 3a):只列本板出现的类型 */}
      {[...new Set(nodes.map((n) => n.category ?? ""))].some((c) => NODE_CATEGORY_COLOR[c]) && (
        <div className="chips" style={{ marginBottom: 6 }}>
          <span className="muted small">节点类型:</span>
          {[...new Set(nodes.map((n) => n.category ?? ""))].filter((c) => NODE_CATEGORY_COLOR[c]).map((c) => (
            <span key={c} className="chip">
              <span style={{ color: NODE_CATEGORY_COLOR[c] }}>●</span> {NODE_CATEGORY_LABEL[c] ?? c}
            </span>
          ))}
        </div>
      )}

      <div className="graph-stage">
      <svg
        ref={svgRef}
        className="graph-svg"
        onPointerDown={onCanvasDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onWheel={onWheel}
      >
        <defs>
          <pattern id="ggrid" width={GRID} height={GRID} patternUnits="userSpaceOnUse">
            <path d={`M ${GRID} 0 L 0 0 0 ${GRID}`} fill="none" stroke="#20242c" strokeWidth={1} />
          </pattern>
        </defs>
        <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
          {board?.grid_on !== 0 && (
            <rect x={-4000} y={-3000} width={9000} height={7000} fill="url(#ggrid)" />
          )}
          {(kindOff.length ? edges.filter((e) => !kindOff.includes(e.kind)) : edges).map((e) => {
            const a = nodeById(e.from_node_id), b = nodeById(e.to_node_id);
            if (!a || !b) return null;
            const p1 = rectAnchor(a, b), p2 = rectAnchor(b, a);
            const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
            const off = edgeOffset(e.id);
            const nx = -(p2.y - p1.y), ny = p2.x - p1.x;
            const len = Math.hypot(nx, ny) || 1;
            const cx = mx + (nx / len) * off, cy = my + (ny / len) * off;
            const color = KIND_COLOR[e.kind] ?? "#7aa2f7";
            const efs = Math.min(22, Math.max(11, 14 / zoom));
            const mid = toScreen({ x: mx + (cx - mx) * 0.5, y: my + (cy - my) * 0.5 });
            return (
              <g key={e.id}>
                <path d={`M ${p1.x} ${p1.y} Q ${cx} ${cy} ${p2.x} ${p2.y}`}
                  fill="none" stroke={color} strokeWidth={2.2}
                  opacity={selected?.type === "edge" && selected.id === e.id ? 1 : 0.8}
                  onPointerDown={(ev) => {
                    ev.stopPropagation();
                    setSelected({ type: "edge", id: e.id });
                  }} />
                <text x={cx} y={cy - 6} textAnchor="middle"
                  fontSize={efs}
                  fill={color} paintOrder="stroke" stroke="var(--panel)" strokeWidth={3 / zoom}
                  style={{ pointerEvents: "none" }}>
                  {truncText(`${e.kind}${e.label ? `·${e.label}` : ""}`, efs * 11.5)}</text>
                {/* 边中点控制点(A5):r6 视觉 + r12 热区(fill none 的 hit-test 用 pointerEvents=all) */}
                <circle cx={mx + (cx - mx) * 0.5} cy={my + (cy - my) * 0.5} r={12}
                  fill="none" pointerEvents="all"
                  onPointerDown={(ev) => {
                    ev.stopPropagation();
                    setEdgeMenu({ eid: e.id, sx: mid.x, sy: mid.y });
                  }} />
                <circle cx={mx + (cx - mx) * 0.5} cy={my + (cy - my) * 0.5} r={6}
                  fill="var(--panel)" stroke={color} strokeWidth={1.6}
                  style={{ pointerEvents: "none" }} />
              </g>
            );
          })}
          {nodes.map((n) => {
            const isHot = hotNode === n.id;
            const isSel = selected?.type === "node" && selected.id === n.id;
            // 顺手修:标签框内换行(≤2 行)+超长省略;悬浮 <title> 看全名
            const labelLines = wrapText(n.label || "", NODE_W - 18, 2);
            const two = labelLines.length > 1;
            const labelBase = n.sub_label ? (two ? -9 : -3) : (two ? -2 : 5);
            const catColor = NODE_CATEGORY_COLOR[n.category ?? ""] ?? null;
            return (
              <g key={n.id} onPointerDown={(ev) => onNodeDown(ev, n)}
                style={{ cursor: "grab" }}>
                <title>{n.label}{n.sub_label ? `\n${n.sub_label}` : ""}</title>
                {isHot && sideAnchors(n).map((a, i) => (
                  <circle key={i} cx={a.pt.x} cy={a.pt.y} r={9} fill="none"
                    stroke="var(--accent)" strokeWidth={2} className="hot-anchor" />
                ))}
                <rect x={n.x - NODE_W / 2} y={n.y - NODE_H / 2} width={NODE_W} height={NODE_H}
                  rx={9} fill="var(--panel)"
                  stroke={isSel || isHot ? "var(--accent)" : catColor ?? "var(--border)"}
                  strokeWidth={isSel || isHot ? 2.2 : catColor ? 1.8 : 1.4} />
                {labelLines.map((ln, i) => (
                  <text key={i} x={n.x} y={n.y + labelBase + i * 15} textAnchor="middle"
                    fontSize={13} fill="var(--text)">{ln}</text>
                ))}
                {n.sub_label && (
                  <text x={n.x} y={n.y + (two ? 20 : 15)} textAnchor="middle" fontSize={10}
                    fill="var(--muted)">{truncText(n.sub_label, NODE_W - 12)}</text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="graph-zoombar">
        <button title="放大" onClick={() => zoomBy(1.25)}>＋</button>
        <button title="缩小" onClick={() => zoomBy(1 / 1.25)}>－</button>
        <button title="重置 1:1" onClick={resetView}>1:1</button>
      </div>
      </div>

      {/* A4 自动连线小表单 */}
      {linkForm && (
        <div className="dialog" style={{ position: "fixed", right: 20, top: 90, zIndex: 80, width: 300 }}>
          <p><b>自动连线</b>:{nodeById(linkForm.from)?.label} → {nodeById(linkForm.to)?.label}</p>
          <div className="row">
            <input placeholder="关系名(可空)" value={linkLabel}
              onChange={(e) => setLinkLabel(e.target.value)} />
            <select value={linkKind} onChange={(e) => setLinkKind(e.target.value)}>
              {EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}
            </select>
          </div>
          <div className="row">
            <button className="primary" onClick={confirmLink}>建立</button>
            <button onClick={() => setLinkForm(null)}>取消</button>
          </div>
        </div>
      )}

      {/* A5 边中点菜单 */}
      {edgeMenu && edgeMenuEdge && (
        <div className="graph-menu" style={{ left: edgeMenu.sx + 12, top: edgeMenu.sy + 8 }}>
          <button onClick={() => addDerived(edgeMenu.eid)}>加派生节点</button>
          <button onClick={async () => {
            const label = await uiPrompt("新标签", edgeMenuEdge.label);
            if (label !== null) api.patchGraphEdge(edgeMenu.eid, { label })
              .then(() => { load(); setEdgeMenu(null); }).catch((e) => setError(String(e)));
          }}>改标签</button>
          <select value={edgeMenuEdge.kind}
            onChange={(e) => api.patchGraphEdge(edgeMenu.eid, { kind: e.target.value })
              .then(() => { load(); setEdgeMenu(null); }).catch((er) => setError(String(er)))}>
            {EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}
          </select>
          <button className="danger-link" onClick={() => {
            api.deleteGraphEdge(edgeMenu.eid)
              .then(() => { load(); setEdgeMenu(null); }).catch((e) => setError(String(e)));
          }}>删除连线</button>
          <button className="link" onClick={() => setEdgeMenu(null)}>关闭</button>
        </div>
      )}

      {/* 侧栏:选中节点/边详情 + 对话;板级对话 */}
      {(selNode || selEdge || showBoardChat) && (
        <div className="node-drawer">
          <div className="row spread">
            <b>{selNode ? "图谱节点" : selEdge ? "图谱连线" : `整板对话·${board?.name}`}</b>
            <button className="link" onClick={() => { setSelected(null); setShowBoardChat(false); }}>关闭 ×</button>
          </div>
          {selNode && (
            <>
              <div className="row spread">
                <b>{selNode.label}</b>
                {onShowLinks && (
                  <button className="link"
                    onClick={() => onShowLinks("graph_node", selNode.id, selNode.label)}>
                    🔗 关联
                  </button>
                )}
              </div>
              <div className="form">
                <label>名称
                  <input defaultValue={selNode.label} key={selNode.id + "l"}
                    onBlur={(e) => e.target.value !== selNode.label &&
                      api.patchGraphNode(selNode.id, { label: e.target.value }).then(load)} />
                </label>
                <label>副标题
                  <input defaultValue={selNode.sub_label ?? ""} key={selNode.id + "s"}
                    onBlur={(e) => e.target.value !== (selNode.sub_label ?? "") &&
                      api.patchGraphNode(selNode.id, { sub_label: e.target.value }).then(load)} />
                </label>
              </div>
              <div className="row">
                <button onClick={async () => {
                  if (await uiConfirm(`删除节点「${selNode.label}」及其连线?`)) {
                    api.deleteGraphNode(selNode.id).then(() => { setSelected(null); load(); });
                  }
                }}>删除节点</button>
              </div>
              <ChatPanel
                projectId={board?.project_id ?? null}
                ownerType="graph_node"
                ownerId={selNode.id}
                defaultSessionName={`节点讨论·${selNode.label}`}
                allowPresets
                getAdoptBefore={getAdoptBefore}
                getAdoptAnchor={getAdoptAnchor}
                onAdopted={load}
              />
            </>
          )}
          {selEdge && (
            <>
              <div className="form">
                <label>关系名
                  <input defaultValue={selEdge.label} key={selEdge.id + "l"}
                    onBlur={(e) => e.target.value !== selEdge.label &&
                      api.patchGraphEdge(selEdge.id, { label: e.target.value }).then(load)} />
                </label>
                <label>类别
                  <select value={selEdge.kind} key={selEdge.id + "k"}
                    onChange={(e) => api.patchGraphEdge(selEdge.id, { kind: e.target.value }).then(load)}>
                    {EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}
                  </select>
                </label>
              </div>
              <div className="row">
                <button onClick={async () => {
                  if (await uiConfirm("删除这条连线?")) {
                    api.deleteGraphEdge(selEdge.id).then(() => { setSelected(null); load(); });
                  }
                }}>删除连线</button>
              </div>
              <ChatPanel
                projectId={board?.project_id ?? null}
                ownerType="graph_edge"
                ownerId={selEdge.id}
                defaultSessionName={`连线讨论`}
                allowPresets
                getAdoptBefore={getAdoptBefore}
                getAdoptAnchor={getAdoptAnchor}
                onAdopted={load}
              />
            </>
          )}
          {showBoardChat && !selNode && !selEdge && (
            <ChatPanel
              projectId={board?.project_id ?? null}
              ownerType="graph_board"
              ownerId={boardId}
              defaultSessionName={`整板发散·${board?.name}`}
              allowPresets
              getAdoptAnchor={getAdoptAnchor}
              onAdopted={load}
            />
          )}
        </div>
      )}
    </div>
  );
}
