import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { NODE_CATEGORY_COLOR, NODE_CATEGORY_LABEL } from "../graphLayout";

/**
 * 批次三⑥:全书总览图谱(执行书追加范围⑥ v1)——聚合全部板的节点/边成一张
 * 超大全书图谱,按板序分象限铺开。数据与单板同源(每次进入重新拉取)=
 * 单板任何调整后回到总览即最新,无需同步逻辑。v1 只读:平移缩放+类别图例
 * 过滤+点节点跳对应单板(编辑回单板做;编辑对齐=执行书 v2)。
 */
const BOARD_GAP_X = 900;    // 批次五:1500→900(用户体感:板块距离太大太分散)
const BOARD_GAP_Y = 640;    // 1100→640 同口径收紧
const NODE_W = 140;
const NODE_H = 36;

interface OverviewNode {
  id: string; board_id: string; board_name: string; label: string;
  category: string; x: number; y: number;
}

export default function GraphOverview({ pid, onOpenBoard, onBack }: {
  pid: string;
  onOpenBoard: (boardId: string) => void;
  onBack: () => void;
}) {
  const [data, setData] = useState<null | {
    boards: { board_id: string; kind: string; name: string;
      nodes: { id: string; label: string; category: string; x: number; y: number }[];
      edges: { id: string; from_node_id: string; to_node_id: string; label: string }[];
    }[];
    board_count: number; node_count: number; edge_count: number;
  }>(null);
  const [error, setError] = useState("");
  const [pan, setPan] = useState({ x: 40, y: 30 });
  const [scale, setScale] = useState(0.8);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [dragState, setDragState] = useState<{ sx: number; sy: number; px: number; py: number } | null>(null);

  const [fitted, setFitted] = useState(false);
  useEffect(() => {
    api.graphOverview(pid).then(setData)
      .catch((e) => setError(String(e.message || e)));
  }, [pid]);

  const laid = useMemo(() => {
    if (!data) return null;
    const nodes: OverviewNode[] = [];
    const edges: { id: string; from: string; to: string; label: string }[] = [];
    const pos = new Map<string, OverviewNode>();
    data.boards.forEach((b, i) => {
      const ox = (i % 3) * BOARD_GAP_X;
      const oy = Math.floor(i / 3) * BOARD_GAP_Y;
      for (const n of b.nodes) {
        const p: OverviewNode = {
          id: n.id, board_id: b.board_id, board_name: b.name,
          label: n.label, category: n.category,
          x: ox + n.x, y: oy + n.y,
        };
        pos.set(n.id, p);
        nodes.push(p);
      }
      for (const e of b.edges) {
        edges.push({ id: e.id, from: e.from_node_id, to: e.to_node_id, label: e.label });
      }
    });
    return { nodes, edges, pos };
  }, [data]);

  const cats = useMemo(
    () => [...new Set((laid?.nodes ?? []).map((n) => n.category).filter(Boolean))],
    [laid]);
  const visible = (c: string) => !hidden.has(c);

  // 进入总览自动适配:按全部节点包围盒缩放平移一次(防多板象限铺开后只见第一板);
  // 终审修复:宽高实测(svg ref),右栏窄容器下写死 1000 会把内容推到视口外
  const svgRef = useRef<SVGSVGElement | null>(null);
  useEffect(() => {
    if (!laid || fitted || laid.nodes.length === 0) return;
    const svgW = svgRef.current?.clientWidth || 1000;
    const svgH = svgRef.current?.clientHeight || 620;
    const xs = laid.nodes.map((n) => n.x), ys = laid.nodes.map((n) => n.y);
    const minX = Math.min(...xs) - NODE_W, maxX = Math.max(...xs) + NODE_W;
    const minY = Math.min(...ys) - NODE_H, maxY = Math.max(...ys) + NODE_H;
    const k = Math.min(1, Math.min(svgW / (maxX - minX), svgH / (maxY - minY)));
    setScale(+Math.max(0.3, k).toFixed(3));
    setPan({
      x: Math.round((svgW - (maxX + minX) * k) / 2),
      y: Math.round((svgH - (maxY + minY) * k) / 2),
    });
    setFitted(true);
  }, [laid, fitted]);
  const setSvgRef = (el: SVGSVGElement | null) => { svgRef.current = el; };

  if (error) {
    return <div><p className="error">{error}</p>
      <button className="link" onClick={onBack}>← 返回图谱中心</button></div>;
  }
  if (!data || !laid) return <p className="muted small">总览加载中…</p>;

  const zoom = (k: number) =>
    setScale((s) => Math.min(2, Math.max(0.3, +(s * k).toFixed(3))));

  return (
    <div>
      <div className="row spread">
        <div className="row">
          <button className="link" onClick={onBack}>← 返回图谱中心</button>
          <b>🌐 全书总览</b>
          <span className="muted small">
            {data.board_count} 板 · {data.node_count} 节点 · {data.edge_count} 连线
          </span>
        </div>
        <div className="row">
          {[...new Set(data.boards.map((b) => b.name))].length > 0 && cats.map((c) => (
            <button key={c} className={visible(c) ? "badge info" : "badge"}
              title={visible(c) ? "点击隐藏该类" : "点击显示该类"}
              onClick={() => setHidden((s) => {
                const next = new Set(s);
                if (next.has(c)) next.delete(c); else next.add(c);
                return next;
              })}>{NODE_CATEGORY_LABEL[c] ?? c}</button>
          ))}
          <button onClick={() => zoom(1.25)}>＋</button>
          <button onClick={() => zoom(0.8)}>－</button>
          <button onClick={() => { setPan({ x: 40, y: 30 }); setScale(0.8); }}>1:1</button>
        </div>
      </div>
      <svg ref={setSvgRef} width="100%" height="620" className="graph-svg"
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          setDragState({ sx: e.clientX, sy: e.clientY, px: pan.x, py: pan.y });
          (e.target as Element).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!dragState) return;
          setPan({ x: dragState.px + (e.clientX - dragState.sx), y: dragState.py + (e.clientY - dragState.sy) });
        }}
        onPointerUp={() => setDragState(null)}
      >
        <g transform={`translate(${pan.x},${pan.y}) scale(${scale})`}>
          {laid.edges.map((e) => {
            const a = laid.pos.get(e.from);
            const b = laid.pos.get(e.to);
            if (!a || !b || !visible(a.category) || !visible(b.category)) return null;
            return <line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="var(--border)" strokeWidth={1.5} />;
          })}
          {laid.nodes.filter((n) => visible(n.category)).map((n) => {
            const color = NODE_CATEGORY_COLOR[n.category] ?? "var(--accent)";
            return (
              <g key={n.id} style={{ cursor: "pointer" }}
                onClick={() => onOpenBoard(n.board_id)}>
                <rect x={n.x - NODE_W / 2} y={n.y - NODE_H / 2} width={NODE_W}
                  height={NODE_H} rx={6} fill="var(--panel)" stroke={color} />
                <text x={n.x} y={n.y + 4} textAnchor="middle" fill="var(--text)"
                  fontSize={12} style={{ pointerEvents: "none" }}>
                  {n.label.length > 9 ? `${n.label.slice(0, 9)}…` : n.label}
                </text>
                <title>{n.board_name} · {n.label}(点击进入该板编辑)</title>
              </g>
            );
          })}
        </g>
      </svg>
      <p className="muted small">
        数据与单板同源:单板里拖动/连线后回到总览即最新;点节点进入该板编辑。
        板按象限铺开,跨板关系呈现=执行书 v2(白名单语义互联)。
      </p>
    </div>
  );
}
