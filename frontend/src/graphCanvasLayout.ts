/**
 * 图谱画布几何/配色/卡型纯件(大文件拆分批 2026-09-10 自 GraphCanvas.tsx 抽出;
 * 纯移动零行为变化):网格吸附定寸 / 边类别配色 / 边缘锚点几何 / 节点卡型判定。
 * 与 graphLayout.ts(定宽换行与层级布局)同族——零组件依赖,可单独单测。
 */
import type { GraphEdge, GraphNode } from "./types";
import { NODE_H, NODE_W, type Pt } from "./graphLayout";

/** 网格吸附 20px(布局/换行纯计算件已拆 ../graphLayout,审计 S10)。 */
export const GRID = 20;

export const KIND_COLOR: Record<string, string> = {
  亲情: "#e0af68", 爱情: "#f7768e", 友情: "#9ece6a", 敌对: "#bb9af7", 其他: "#7aa2f7",
  因果: "#7aa2f7", 并行: "#9ece6a", 承接: "#e0af68", 持有: "#e0af68", 来源: "#9ece6a",
  去向: "#7aa2f7", 相邻: "#9ece6a", 通道: "#e0af68", 从属: "#bb9af7", 同盟: "#9ece6a",
  衍生: "#7aa2f7", 克制: "#f7768e", 自由: "#8b93a1",
};
export const EDGE_KINDS = Object.keys(KIND_COLOR);

/** 节点中心 a 朝 b 方向与 a 矩形边框的交点(边缘锚点)。 */
export function rectAnchor(a: Pt, b: Pt): Pt {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (dx === 0 && dy === 0) return a;
  const sx = dx !== 0 ? (NODE_W / 2) / Math.abs(dx) : Infinity;
  const sy = dy !== 0 ? (NODE_H / 2) / Math.abs(dy) : Infinity;
  const s = Math.min(sx, sy);
  return { x: a.x + dx * s, y: a.y + dy * s };
}

/** 四边中点锚点(自动连线热区)。 */
export function sideAnchors(n: GraphNode): { side: string; pt: Pt }[] {
  return [
    { side: "上", pt: { x: n.x, y: n.y - NODE_H / 2 } },
    { side: "下", pt: { x: n.x, y: n.y + NODE_H / 2 } },
    { side: "左", pt: { x: n.x - NODE_W / 2, y: n.y } },
    { side: "右", pt: { x: n.x + NODE_W / 2, y: n.y } },
  ];
}

export function nodeById(nodes: GraphNode[], id: string): GraphNode | undefined {
  return nodes.find((n) => n.id === id);
}

// 同对节点多线偏移(A6):按出现序给法向偏移
export function edgeOffset(edges: GraphEdge[], eid: string): number {
  const e = edges.find((x) => x.id === eid)!;
  const same = edges.filter((x) =>
    (x.from_node_id === e.from_node_id && x.to_node_id === e.to_node_id) ||
    (x.from_node_id === e.to_node_id && x.to_node_id === e.from_node_id));
  const idx = same.findIndex((x) => x.id === eid);
  return (idx - (same.length - 1) / 2) * 34;
}

// 批次三④自由画布三卡型:文本卡(默认)/清单卡(style.items)/实体链接卡(style.ref)
export function cardOf(n: GraphNode): string {
  return String((n.style as Record<string, unknown>)?.card ?? "text");
}

export function cardItems(n: GraphNode): { text: string; done: boolean }[] {
  const it = (n.style as Record<string, unknown>)?.items;
  return Array.isArray(it) ? (it as { text: string; done: boolean }[]) : [];
}
