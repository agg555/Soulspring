/**
 * 图谱画布展示件(大文件拆分批 2026-09-10 自 GraphCanvas.tsx 抽出;纯移动零行为变化):
 * 边层 / 节点层 / 图例两行。全是纯渲染,交互行为由 GraphCanvas 以回调传入——
 * 无内部状态,故抽离后渲染时序与原来逐帧一致。
 */
import type { GraphEdge, GraphNode } from "../../types";
import { NODE_CATEGORY_COLOR, NODE_CATEGORY_LABEL, NODE_H, NODE_W, HOOK_STATUS_COLOR, truncText, wrapText, type Pt } from "../../graphLayout";
import { KIND_COLOR, cardItems, cardOf, edgeOffset, nodeById, rectAnchor, sideAnchors } from "../../graphCanvasLayout";

export function GraphEdgeLayer({
  nodes, edges, kindOff, chapterCap, zoom, pan, selected, onSelectEdge, onOpenMenu,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  kindOff: string[];
  chapterCap: number | null;
  zoom: number;
  pan: Pt;
  selected: { type: "node" | "edge"; id: string } | null;
  onSelectEdge: (eid: string) => void;
  onOpenMenu: (eid: string, sx: number, sy: number) => void;
}) {
  const toScreen = (gp: Pt): Pt => ({ x: gp.x * zoom + pan.x, y: gp.y * zoom + pan.y });
  return (
    <>
      {(kindOff.length ? edges.filter((e) => !kindOff.includes(e.kind)) : edges)
        .filter((e) => chapterCap == null
          || !(Number((e.style as Record<string, unknown>)?.at_chapter) > chapterCap))
        .map((e) => {
          const a = nodeById(nodes, e.from_node_id), b = nodeById(nodes, e.to_node_id);
          if (!a || !b) return null;
          const p1 = rectAnchor(a, b), p2 = rectAnchor(b, a);
          const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
          const off = edgeOffset(edges, e.id);
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
                  onSelectEdge(e.id);
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
                  onOpenMenu(e.id, mid.x, mid.y);
                }} />
              <circle cx={mx + (cx - mx) * 0.5} cy={my + (cy - my) * 0.5} r={6}
                fill="var(--panel)" stroke={color} strokeWidth={1.6}
                style={{ pointerEvents: "none" }} />
            </g>
          );
        })}
    </>
  );
}

export function GraphNodeLayer({
  nodes, boardKind, hotNode, selected, onNodeDown, onNodeMenu, onRename,
}: {
  nodes: GraphNode[];
  boardKind: string | undefined;
  hotNode: string | null;
  selected: { type: "node" | "edge"; id: string } | null;
  onNodeDown: (e: React.PointerEvent, n: GraphNode) => void;
  onNodeMenu: (nid: string, sx: number, sy: number) => void;
  onRename: (n: GraphNode) => void;
}) {
  return (
    <>
      {nodes.map((n) => {
        const isHot = hotNode === n.id;
        const isSel = selected?.type === "node" && selected.id === n.id;
        // 顺手修:标签框内换行(≤2 行)+超长省略;悬浮 <title> 看全名
        const labelLines = wrapText(n.label || "", NODE_W - 18, 2);
        const two = labelLines.length > 1;
        const labelBase = n.sub_label ? (two ? -9 : -3) : (two ? -2 : 5);
        const catColor = NODE_CATEGORY_COLOR[n.category ?? ""] ?? null;
        const hookStatus = boardKind === "hook"
          ? String((n.style as Record<string, unknown>)?.status ?? "埋设") : null;
        const boxColor = hookStatus ? HOOK_STATUS_COLOR[hookStatus] : catColor;
        return (
          <g key={n.id} onPointerDown={(ev) => onNodeDown(ev, n)}
            onContextMenu={(ev) => {
              ev.preventDefault();
              onNodeMenu(n.id, ev.clientX, ev.clientY);
            }}
            onDoubleClick={() => onRename(n)}
            style={{ cursor: "grab" }}>
            <title>{n.label}{n.sub_label ? `\n${n.sub_label}` : ""}</title>
            {isHot && sideAnchors(n).map((a, i) => (
              <circle key={i} cx={a.pt.x} cy={a.pt.y} r={9} fill="none"
                stroke="var(--accent)" strokeWidth={2} className="hot-anchor" />
            ))}
            <rect x={n.x - NODE_W / 2} y={n.y - NODE_H / 2} width={NODE_W} height={NODE_H}
              rx={9} fill="var(--panel)"
              stroke={isSel || isHot ? "var(--accent)" : boxColor ?? "var(--border)"}
              strokeWidth={isSel || isHot ? 2.2 : boxColor ? 1.8 : 1.4} />
            {labelLines.map((ln, i) => (
              <text key={i} x={n.x} y={n.y + labelBase + i * 15} textAnchor="middle"
                fontSize={13} fill="var(--text)">{ln}</text>
            ))}
            {n.sub_label && (
              <text x={n.x} y={n.y + (two ? 20 : 15)} textAnchor="middle" fontSize={10}
                fill="var(--muted)">{truncText(n.sub_label, NODE_W - 12)}</text>
            )}
            {/* 批次三④三卡型角标:清单卡=完成度,链接卡=出处标题 */}
            {cardOf(n) === "checklist" && (() => {
              const items = cardItems(n);
              const done = items.filter((i) => i.done).length;
              return (
                <text x={n.x} y={n.y + (two ? 34 : 29)} textAnchor="middle" fontSize={10}
                  fill="var(--ok, #9ece6a)">☑ {done}/{items.length}</text>
              );
            })()}
            {cardOf(n) === "link" && (() => {
              const ref = ((n.style as Record<string, unknown>)?.ref) as { title?: string } | undefined;
              return (
                <text x={n.x} y={n.y + (two ? 34 : 29)} textAnchor="middle" fontSize={10}
                  fill="var(--accent)">🔗 {truncText(String(ref?.title ?? ""), 12)}</text>
              );
            })()}
          </g>
        );
      })}
    </>
  );
}

export function GraphLegend({
  nodes, edges, kindOff, onToggleKind,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  kindOff: string[];
  onToggleKind: (k: string) => void;
}) {
  return (
    <>
      <div className="chips" style={{ marginBottom: 6 }}>
        <span className="muted small">图例过滤:</span>
        {[...new Set(edges.map((e) => e.kind))].map((k) => (
          <button key={k} className={`chip ${kindOff.includes(k) ? "" : "on"}`}
            onClick={() => onToggleKind(k)}>
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
    </>
  );
}
