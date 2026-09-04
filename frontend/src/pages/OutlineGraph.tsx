import type { OutlineNode } from "../types";
import { wrapText } from "../components/GraphCanvas";

/**
 * 树/图双形态(骨架批拍板 2ab)的图谱形态:大纲树只读图形化(层级自动布局),
 * 点击节点开同一详情抽屉;编辑仍在树形态/抽屉做(AI 引申实现形态,骨架书 §9.2 否决制)。
 * 布局 = 经典整洁树:叶节点顺序排布,父节点横跨子节点居中;状态色描边 + 图例。
 */
const G_NODE_W = 128, G_NODE_H = 42, G_GX = 22, G_GY = 34;

const KIND_LABEL: Record<string, string> = {
  category: "总纲", volume: "卷", arc: "近纲", chapter: "章", scene: "场景",
};
const STATUS_LABEL: Record<string, string> = {
  unwritten: "未写", draft: "草稿", human_editing: "人改中",
  final_review: "待终审", finalized: "定稿",
};
const STATUS_COLOR: Record<string, string> = {
  unwritten: "#8b93a1", draft: "#7aa2f7", human_editing: "#e0af68",
  final_review: "#bb9af7", finalized: "#9ece6a",
};

export default function OutlineGraph({ nodes, matchIds, onOpen }: {
  nodes: OutlineNode[];
  matchIds: Set<string> | null;
  onOpen: (nid: string) => void;
}) {
  const kept = matchIds ? nodes.filter((n) => matchIds.has(n.id)) : nodes;
  const byParent = new Map<string | null, OutlineNode[]>();
  for (const n of kept) {
    const k = n.parent_id ?? null;
    if (!byParent.has(k)) byParent.set(k, []);
    byParent.get(k)!.push(n);
  }
  const pos = new Map<string, { x: number; y: number }>();
  let cursor = 0, maxDepth = 0;
  const place = (id: string, depth: number): number => {
    maxDepth = Math.max(maxDepth, depth);
    const kids = byParent.get(id) ?? [];
    const y = depth * (G_NODE_H + G_GY) + G_NODE_H / 2;
    if (kids.length === 0) {
      const cx = cursor + G_NODE_W / 2;
      cursor += G_NODE_W + G_GX;
      pos.set(id, { x: cx, y });
      return cx;
    }
    const centers = kids.map((k) => place(k.id, depth + 1));
    const cx = (centers[0] + centers[centers.length - 1]) / 2;
    pos.set(id, { x: cx, y });
    return cx;
  };
  for (const r of byParent.get(null) ?? []) place(r.id, 0);
  const width = Math.max(cursor, 200);
  const height = (maxDepth + 1) * (G_NODE_H + G_GY);

  return (
    <div>
      <div className="chips" style={{ marginBottom: 6 }}>
        <span className="muted small">状态色:</span>
        {Object.entries(STATUS_LABEL).map(([k, v]) => (
          <span key={k} className="chip">
            <span style={{ color: STATUS_COLOR[k] }}>●</span> {v}
          </span>
        ))}
        <span className="muted small">(只读;编辑在树形态或点开抽屉)</span>
      </div>
      <div className="outline-graph">
        <svg width={width} height={height}>
          {kept.map((n) => {
            const p = n.parent_id && pos.get(n.parent_id);
            const c = pos.get(n.id);
            if (!p || !c) return null;
            return (
              <path key={"e" + n.id}
                d={`M ${p.x} ${p.y + G_NODE_H / 2} L ${c.x} ${c.y - G_NODE_H / 2}`}
                stroke="var(--border)" strokeWidth={1.6} fill="none" />
            );
          })}
          {kept.map((n) => {
            const c = pos.get(n.id);
            if (!c) return null;
            const lines = wrapText(n.title, G_NODE_W - 16, 2);
            const color = STATUS_COLOR[n.status] ?? "var(--border)";
            return (
              <g key={n.id} style={{ cursor: "pointer" }} onClick={() => onOpen(n.id)}>
                <title>
                  {`${KIND_LABEL[n.kind] ?? n.kind}·${n.title}[${STATUS_LABEL[n.status] ?? n.status}]`}
                </title>
                <rect x={c.x - G_NODE_W / 2} y={c.y - G_NODE_H / 2} width={G_NODE_W} height={G_NODE_H}
                  rx={8} fill="var(--panel)" stroke={color} strokeWidth={1.8} />
                {lines.map((ln, i) => (
                  <text key={i} x={c.x}
                    y={c.y - (lines.length - 1) * 7 + i * 14 + 4}
                    textAnchor="middle" fontSize={12} fill="var(--text)">{ln}</text>
                ))}
                <text x={c.x - G_NODE_W / 2 + 6} y={c.y - G_NODE_H / 2 + 11}
                  fontSize={9} fill={color}>
                  {KIND_LABEL[n.kind] ?? n.kind}·{STATUS_LABEL[n.status] ?? n.status}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
