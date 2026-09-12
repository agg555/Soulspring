/**
 * 图谱画布纯计算件(S10 自 GraphCanvas 拆出,审计 2026-09-06;纯移动零行为变化):
 * 节点定寸 / 定宽换行截断 / 层级整洁树布局 / 伏笔状态泳道布局。
 * 零组件依赖,GraphCanvas 与大纲图谱(OutlineGraph)/时间线(TimelinePanel)共用。
 */
import type { GraphEdge, GraphNode } from "./types";

export const NODE_W = 128, NODE_H = 48;

export type Pt = { x: number; y: number };

/* 节点实体类型着色配套(体感三桶 2026-09-04 拍板 3a):伏笔状态三态序与配色 */
export const HOOK_STATUS_ORDER = ["埋设", "强化", "回收"];
export const HOOK_STATUS_COLOR: Record<string, string> = {
  埋设: "#e0af68", 强化: "#7aa2f7", 回收: "#9ece6a",
};
export const PARENT_EDGE_KINDS = ["从属", "衍生", "承接", "来源"];

// 节点实体类别色/名(批次三⑥自 GraphCanvas 收编纯数据,总览与单板共用一套)
export const NODE_CATEGORY_COLOR: Record<string, string> = {
  worldview: "#7aa2f7", character: "#9ece6a", power: "#bb9af7", faction: "#e0af68",
  map: "#4fd6be", item_economy: "#ff9e64", timeline_event: "#f7768e", free: "#8b93a1",
};
export const NODE_CATEGORY_LABEL: Record<string, string> = {
  worldview: "世界观", character: "角色", power: "力量", faction: "势力",
  map: "地理", item_economy: "物品经济", timeline_event: "事件", free: "自由",
};

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

/** 层级整洁树布局(批次二拍板 B):按 从属/衍生/承接/来源 边定父子;孤立点当根。 */
export function hierarchicalLayout(nodes: GraphNode[], edges: GraphEdge[]): Map<string, Pt> {
  /* 层级布局 v2(批次三③体感 2026-09-06:人物关系板点层级整理全叠一行)。
     根因=旧实现只认 PARENT_EDGE_KINDS 四种边为父子,关系板"亲戚/同盟/因果"
     全被无视→全员当根铺成一行。v2 混合:板内存在从属类边→走原树形算法
     (中心对齐的漂亮树);否则按全部边连通分层(BFS 定层,环安全:已定层不重访,
     纯环/孤点兜底),同层超 6 个自动换子行,长链不再挤一行。 */
  const hasParentKind = edges.some((e) => PARENT_EDGE_KINDS.includes(e.kind));
  if (hasParentKind) {
    const ids = new Set(nodes.map((n) => n.id));
    const parentOf = new Map<string, string>();
    const childrenOf = new Map<string, string[]>();
    const roots: string[] = [];
    for (const e of edges) {
      if (!PARENT_EDGE_KINDS.includes(e.kind) || !ids.has(e.from_node_id)
        || !ids.has(e.to_node_id) || parentOf.has(e.to_node_id)) continue;
      parentOf.set(e.to_node_id, e.from_node_id);
    }
    for (const n of nodes) {
      const pid = parentOf.get(n.id);
      if (pid) {
        if (!childrenOf.has(pid)) childrenOf.set(pid, []);
        childrenOf.get(pid)!.push(n.id);
      } else roots.push(n.id);
    }
    const pos = new Map<string, Pt>();
    let cursor = 80;
    const place = (id: string, depth: number): number => {
      const kids = childrenOf.get(id) ?? [];
      const y = 90 + depth * (NODE_H + 52);
      if (kids.length === 0) {
        const x = cursor + NODE_W / 2;
        cursor += NODE_W + 36;
        pos.set(id, { x, y });
        return x;
      }
      const centers = kids.map((k) => place(k, depth + 1));
      const x = (centers[0] + centers[centers.length - 1]) / 2;
      pos.set(id, { x, y });
      return x;
    };
    for (const r of roots) place(r, 0);
    return pos;
  }
  // 连通分层(全部边参与;from→to 视为父→子方向提示,环靠已定层不重访打破)
  const ids = new Set(nodes.map((n) => n.id));
  const childrenOf = new Map<string, string[]>();
  const hasParent = new Set<string>();
  for (const e of edges) {
    if (!ids.has(e.from_node_id) || !ids.has(e.to_node_id)
      || e.from_node_id === e.to_node_id) continue;
    if (!childrenOf.has(e.from_node_id)) childrenOf.set(e.from_node_id, []);
    childrenOf.get(e.from_node_id)!.push(e.to_node_id);
    hasParent.add(e.to_node_id);
  }
  const depth = new Map<string, number>();
  const queue: string[] = [];
  for (const n of nodes) {
    if (!hasParent.has(n.id)) { depth.set(n.id, 0); queue.push(n.id); }
  }
  if (queue.length === 0 && nodes.length > 0) {   // 纯环兜底:任取一点当根
    depth.set(nodes[0].id, 0);
    queue.push(nodes[0].id);
  }
  for (let qi = 0; qi < queue.length; qi++) {
    const d = depth.get(queue[qi]) ?? 0;
    for (const k of childrenOf.get(queue[qi]) ?? []) {
      if (!depth.has(k)) { depth.set(k, d + 1); queue.push(k); }
    }
  }
  const maxD = Math.max(0, ...depth.values());
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, maxD + 1);
  const levels = new Map<number, string[]>();
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    if (!levels.has(d)) levels.set(d, []);
    levels.get(d)!.push(n.id);
  }
  const pos = new Map<string, Pt>();
  const PER_ROW = 6;
  for (const [d, members] of [...levels.entries()].sort((x, y) => x[0] - y[0])) {
    members.forEach((id, i) => {
      const row = Math.floor(i / PER_ROW);
      const col = i % PER_ROW;
      pos.set(id, {
        x: 80 + col * (NODE_W + 48) + NODE_W / 2,
        y: 90 + d * (NODE_H + 52) + row * (NODE_H + 30),
      });
    });
  }
  return pos;
}

/** 伏笔状态泳道布局:埋设/强化/回收 三列,列内按建板顺序堆叠。 */
export function statusLaneLayout(nodes: GraphNode[]): Map<string, Pt> {
  const pos = new Map<string, Pt>();
  const rowIdx: Record<string, number> = {};
  for (const n of nodes) {
    const st = String((n.style as Record<string, unknown>)?.status ?? "埋设");
    const col = Math.max(0, HOOK_STATUS_ORDER.indexOf(st));
    const row = rowIdx[st] ?? 0;
    rowIdx[st] = row + 1;
    pos.set(n.id, { x: 150 + col * 230, y: 90 + row * (NODE_H + 40) + NODE_H / 2 });
  }
  return pos;
}
