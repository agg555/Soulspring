import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { OutlineNode } from "../types";
import { wrapText } from "../graphLayout";
import { uiConfirm, uiPrompt } from "../components/uiConfirm";

/**
 * 树/图双形态(骨架批拍板 2ab)的图谱形态。批次五 v2(2026-09-06 用户"对齐图谱"):
 * 在原自动布局+点击开抽屉+双击改名+章状态快切之上,补齐图谱同款交互——
 * 平移(空白拖拽)/缩放(滚轮+＋－/1:1)/节点拖动(位置 localStorage
 * `outlinegraph:pos:<pid>` 持久化,拖动超阈值抑制误开抽屉)/右键菜单全类型扩容。
 *
 * 批次七⑦ 千章 LOD(执行书⑤:低配设备打开千章图谱可用):
 * - LOD 细节层次:zoom<0.55 远景只画框(不画字/徽标/tooltip);<0.9 中景省角标;全画。
 * - 默认收起卷下层级:章数>120 的大书首次打开只铺卷(点卷缘 +/− 展开收起,
 *   localStorage 持久化);搜索态(matchIds)不收叠=现状不变。
 * - 按卷过滤:下拉选卷只看该卷子树(自动展开)。
 * - 性能:布局与节点 JSX 双层 memo——pan/zoom 只改 transform,不再每帧重排
 *   2000 组(React 对相同元素引用直接跳过 diff);打开耗时/渲染数在工具条可见。
 */
const G_NODE_W = 128, G_NODE_H = 42, G_GX = 22, G_GY = 34;

const KIND_LABEL: Record<string, string> = {
  category: "总纲", volume: "卷", arc: "近纲", chapter: "章", scene: "场景", topic: "子题",
};
const STATUS_LABEL: Record<string, string> = {
  unwritten: "未写", draft: "草稿", human_editing: "人改中",
  final_review: "待终审", finalized: "定稿",
};
const STATUS_COLOR: Record<string, string> = {
  unwritten: "#8b93a1", draft: "#7aa2f7", human_editing: "#e0af68",
  final_review: "#bb9af7", finalized: "#9ece6a",
};

type Pos = { x: number; y: number };

export default function OutlineGraph({ pid, nodes, matchIds, onOpen, editable, onChanged }: {
  pid: string;
  nodes: OutlineNode[];
  matchIds: Set<string> | null;
  onOpen: (nid: string) => void;
  /** 少量编辑(拍板 C,2026-09-05):双击改名 + 右键快切章状态;批次五扩容右键菜单 */
  editable?: boolean;
  onChanged?: () => void;
}) {
  const [menu, setMenu] = useState<{ x: number; y: number; node: OutlineNode } | null>(null);
  const [pan, setPan] = useState({ x: 24, y: 16 });
  const [zoom, setZoom] = useState(1);
  const [dragPan, setDragPan] = useState<{ sx: number; sy: number; px: number; py: number } | null>(null);
  // 节点拖动:覆盖坐标(localStorage 持久化)+拖动中抑制点击开抽屉
  const [override, setOverride] = useState<Record<string, Pos>>({});
  const nodeDrag = useRef<{ id: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  // ── 批次七⑦:卷收叠/按卷过滤/LOD/打开计时 ──
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [volFilter, setVolFilter] = useState("");
  const [openMs, setOpenMs] = useState<number | null>(null);
  const initRef = useRef(false);
  const panRef = useRef(pan);
  panRef.current = pan;

  const posKey = `outlinegraph:pos:${pid}`;
  const collapsedKey = `outlinegraph:collapsed:${pid}`;
  useEffect(() => {
    try {
      const raw = localStorage.getItem(posKey);
      if (raw) setOverride(JSON.parse(raw));
    } catch { /* 忽略 */ }
  }, [posKey]);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    try {
      const raw = localStorage.getItem(collapsedKey);
      if (raw) { setCollapsed(new Set(JSON.parse(raw) as string[])); return; }
    } catch { /* 忽略 */ }
    // 默认收起卷下层级:只对大书生效(千章判据);小书保持零配置现状
    if (nodes.filter((n) => n.kind === "chapter").length > 120) {
      setCollapsed(new Set(nodes.filter((n) => n.kind === "volume").map((n) => n.id)));
    }
    const t0 = performance.now();
    requestAnimationFrame(() => setOpenMs(Math.round(performance.now() - t0)));
  }, [collapsedKey, nodes]);

  const toggleVol = (id: string) => {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      try { localStorage.setItem(collapsedKey, JSON.stringify([...next])); } catch { /* 忽略 */ }
      return next;
    });
  };

  const kept = matchIds ? nodes.filter((n) => matchIds.has(n.id)) : nodes;

  // 可见集 = kept −(按卷过滤时其它卷子树)−(收叠卷的后代);搜索态不收叠
  const visible = useMemo(() => {
    if (matchIds) return kept;
    let base = kept;
    if (volFilter) {
      const byP = new Map<string | null, OutlineNode[]>();
      for (const n of kept) {
        const k = n.parent_id ?? null;
        if (!byP.has(k)) byP.set(k, []);
        byP.get(k)!.push(n);
      }
      const keep = new Set<string>();
      const walk = (id: string) => {
        keep.add(id);
        for (const c of byP.get(id) ?? []) walk(c.id);
      };
      walk(volFilter);
      base = kept.filter((n) => keep.has(n.id));
    }
    if (collapsed.size === 0) return base;
    const byP = new Map<string | null, OutlineNode[]>();
    for (const n of base) {
      const k = n.parent_id ?? null;
      if (!byP.has(k)) byP.set(k, []);
      byP.get(k)!.push(n);
    }
    const out: OutlineNode[] = [];
    const walk = (list: OutlineNode[], hidden: boolean) => {
      for (const n of list) {
        if (hidden) continue;
        out.push(n);
        walk(byP.get(n.id) ?? [], collapsed.has(n.id));
      }
    };
    walk(byP.get(null) ?? [], false);
    return out;
  }, [kept, matchIds, collapsed, volFilter]);

  // 布局 memo:pan/zoom/拖动不重算(批次七⑦性能件)
  const layout = useMemo(() => {
    const byParent = new Map<string | null, OutlineNode[]>();
    for (const n of visible) {
      const k = n.parent_id ?? null;
      if (!byParent.has(k)) byParent.set(k, []);
      byParent.get(k)!.push(n);
    }
    const pos = new Map<string, Pos>();
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
    return { pos };
  }, [visible]);

  // 子计数按全书计(kept):收叠卷的子级不可见但计数必须保留,
  // 否则展开按钮(+N)永远不出现(实测 2026-09-08 修)
  const fullChildCount = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of kept) {
      if (n.parent_id) m.set(n.parent_id, (m.get(n.parent_id) ?? 0) + 1);
    }
    return m;
  }, [kept]);

  const finalPos = (id: string): Pos => override[id] ?? layout.pos.get(id) ?? { x: 0, y: 0 };

  const persistOverride = (next: Record<string, Pos>) => {
    setOverride(next);
    try { localStorage.setItem(posKey, JSON.stringify(next)); } catch { /* 忽略 */ }
  };

  const zoomStep = (k: number) =>
    setZoom((z) => Math.min(2, Math.max(0.3, +(z * k).toFixed(3))));

  // LOD 档位:0 远景只画框 / 1 中景无角标 / 2 全细节
  const lod: 0 | 1 | 2 = zoom < 0.55 ? 0 : zoom < 0.9 ? 1 : 2;

  // 节点+边 JSX memo:pan/zoom 变化时元素引用不变,React 跳过 2000 组 diff
  const body = useMemo(() => {
    const edges = visible.map((n) => {
      const p = n.parent_id && finalPos(n.parent_id);
      const c = finalPos(n.id);
      if (!p || !c) return null;
      return (
        <path key={"e" + n.id}
          d={`M ${p.x} ${p.y + G_NODE_H / 2} L ${c.x} ${c.y - G_NODE_H / 2}`}
          stroke="var(--border)" strokeWidth={1.6} fill="none" />
      );
    });
    const nodesJsx = visible.map((n) => {
      const c = finalPos(n.id);
      const lines = lod === 0 ? [] : wrapText(n.title, G_NODE_W - 16, 2);
      const color = STATUS_COLOR[n.status] ?? "var(--border)";
      const kids = fullChildCount.get(n.id) ?? 0;
      const isVol = n.kind === "volume" && kids > 0 && !matchIds;
      return (
        <g key={n.id} style={{ cursor: "grab" }}
          onPointerDown={(ev) => {
            if (ev.button !== 0) return;
            ev.stopPropagation();
            const c0 = finalPos(n.id);
            nodeDrag.current = { id: n.id, sx: ev.clientX, sy: ev.clientY, ox: c0.x, oy: c0.y, moved: false };
            (ev.target as Element).setPointerCapture?.(ev.pointerId);
          }}
          onClick={() => {
            if (suppressClick.current) { suppressClick.current = false; return; }
            onOpen(n.id);
          }}
          onDoubleClick={async (ev) => {
            if (!editable) return;
            ev.stopPropagation();
            const nt = await uiPrompt("节点标题", n.title);
            if (nt !== null && nt.trim() && nt !== n.title) {
              await api.outlineUpdate(n.id, { title: nt.trim() });
              onChanged?.();
            }
          }}
          onContextMenu={(ev) => {
            if (!editable) return;
            ev.preventDefault();
            ev.stopPropagation();
            setMenu({ x: ev.clientX, y: ev.clientY, node: n });
          }}>
          {lod > 0 && (
            <title>
              {`${KIND_LABEL[n.kind] ?? n.kind}·${n.title}[${STATUS_LABEL[n.status] ?? n.status}]`
                + (n.body ? `\n${n.body.slice(0, 100)}${n.body.length > 100 ? "…" : ""}` : "")}
            </title>
          )}
          <rect x={c.x - G_NODE_W / 2} y={c.y - G_NODE_H / 2} width={G_NODE_W} height={G_NODE_H}
            rx={8} fill="var(--panel)" stroke={color} strokeWidth={1.8} />
          {lines.map((ln, i) => (
            <text key={i} x={c.x}
              y={c.y - (lines.length - 1) * 7 + i * 14 + 4}
              textAnchor="middle" fontSize={12} fill="var(--text)">{ln}</text>
          ))}
          {lod > 1 && (
            <text x={c.x - G_NODE_W / 2 + 6} y={c.y - G_NODE_H / 2 + 11}
              fontSize={9} fill={color}>
              {KIND_LABEL[n.kind] ?? n.kind}·{STATUS_LABEL[n.status] ?? n.status}
            </text>
          )}
          {isVol && (
            <g onClick={(ev) => { ev.stopPropagation(); toggleVol(n.id); }}
              style={{ cursor: "pointer" }}>
              <circle cx={c.x + G_NODE_W / 2 - 2} cy={c.y - G_NODE_H / 2 + 2}
                r={8} fill={collapsed.has(n.id) ? "var(--accent)" : "var(--panel)"}
                stroke={color} strokeWidth={1.2} />
              <text x={c.x + G_NODE_W / 2 - 2} y={c.y - G_NODE_H / 2 + 6}
                textAnchor="middle" fontSize={11}
                fill={collapsed.has(n.id) ? "var(--bg)" : "var(--text)"}>
                {collapsed.has(n.id) ? `+${kids}` : "−"}
              </text>
            </g>
          )}
        </g>
      );
    });
    return <>{edges}{nodesJsx}</>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, layout, fullChildCount, override, lod, collapsed, matchIds, editable, onOpen, onChanged]);

  const volumes = nodes.filter((n) => n.kind === "volume");

  return (
    <div>
      <div className="chips" style={{ marginBottom: 6 }}>
        <span className="muted small">状态色:</span>
        {Object.entries(STATUS_LABEL).map(([k, v]) => (
          <span key={k} className="chip">
            <span style={{ color: STATUS_COLOR[k] }}>●</span> {v}
          </span>
        ))}
        <span className="row" style={{ marginLeft: "auto", gap: 4 }}>
          {volumes.length > 1 && (
            <select value={volFilter} title="按卷过滤(批次七⑦)"
              onChange={(e) => setVolFilter(e.target.value)}>
              <option value="">全部卷</option>
              {volumes.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
            </select>
          )}
          <button onClick={() => zoomStep(1.25)}>＋</button>
          <button onClick={() => zoomStep(0.8)}>－</button>
          <button onClick={() => { setPan({ x: 24, y: 16 }); setZoom(1); }}>1:1</button>
        </span>
        <span className="muted small">
          {openMs != null && <>打开 {openMs}ms · </>}
          渲染 {visible.length}/{nodes.length} 节点
          {lod === 0 && " · 远景只画框"} ·
        </span>
        <span className="muted small">(空白拖拽平移·滚轮缩放·卷缘 +/− 展开收起·节点可拖动)</span>
      </div>
      <div className="outline-graph">
        <svg width="100%" height={560}
          onPointerDown={(e) => {
            if (e.button !== 0) return;
            setDragPan({ sx: e.clientX, sy: e.clientY, px: panRef.current.x, py: panRef.current.y });
            (e.target as Element).setPointerCapture?.(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (nodeDrag.current) {
              const d = nodeDrag.current;
              const dx = (e.clientX - d.sx) / zoom, dy = (e.clientY - d.sy) / zoom;
              if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 5) d.moved = true;
              setOverride((cur) => ({ ...cur, [d.id]: { x: d.ox + dx, y: d.oy + dy } }));
            } else if (dragPan) {
              setPan({ x: dragPan.px + (e.clientX - dragPan.sx), y: dragPan.py + (e.clientY - dragPan.sy) });
            }
          }}
          onPointerUp={() => {
            if (nodeDrag.current) {
              const d = nodeDrag.current;
              if (d.moved) {
                suppressClick.current = true;
                setOverride((cur) => {
                  persistOverride(cur);   // 落盘最终位置
                  return cur;
                });
              }
              nodeDrag.current = null;
            }
            setDragPan(null);
          }}
          onWheel={(e) => {
            e.preventDefault();
            zoomStep(e.deltaY < 0 ? 1.1 : 0.9);
          }}>
          <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
            {body}
          </g>
        </svg>
      </div>
      {menu && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 95 }}
            onClick={() => setMenu(null)} onContextMenu={(e) => { e.preventDefault(); setMenu(null); }} />
          <div className="ctx-menu" style={{ left: menu.x, top: menu.y }}>
            <div className="muted small" style={{ padding: "2px 8px" }}>
              {KIND_LABEL[menu.node.kind] ?? menu.node.kind}·{menu.node.title.slice(0, 14)}
            </div>
            <button className="link" style={{ display: "block", width: "100%", textAlign: "left", padding: "3px 10px" }}
              onClick={() => { onOpen(menu.node.id); setMenu(null); }}>打开详情</button>
            {menu.node.kind === "volume" && (fullChildCount.get(menu.node.id) ?? 0) > 0 && !matchIds && (
              <button className="link" style={{ display: "block", width: "100%", textAlign: "left", padding: "3px 10px" }}
                onClick={() => { toggleVol(menu.node.id); setMenu(null); }}>
                {collapsed.has(menu.node.id) ? `展开子级(${fullChildCount.get(menu.node.id)})` : "收起子级"}
              </button>
            )}
            {editable && (
              <button className="link" style={{ display: "block", width: "100%", textAlign: "left", padding: "3px 10px" }}
                onClick={async () => {
                  const nt = await uiPrompt("节点标题", menu.node.title);
                  if (nt !== null && nt.trim() && nt !== menu.node.title) {
                    await api.outlineUpdate(menu.node.id, { title: nt.trim() });
                    onChanged?.();
                  }
                  setMenu(null);
                }}>改名</button>
            )}
            {editable && menu.node.kind === "chapter" && (
              <>
                <div className="muted small" style={{ padding: "2px 8px" }}>快切状态</div>
                {Object.entries(STATUS_LABEL).map(([k, v]) => (
                  <button key={k} className="link" style={{ display: "block", width: "100%", textAlign: "left", padding: "3px 10px" }}
                    onClick={async () => {
                      // 二期②:定稿解封二次确认(从图谱右键快切同样把关)
                      if (menu.node.status === "finalized" && k !== "finalized" &&
                          !(await uiConfirm(`「${menu.node.title}」已定稿,解封回「${v}」?`))) {
                        setMenu(null);
                        return;
                      }
                      await api.outlineStatus(menu.node.id, k);
                      setMenu(null);
                      onChanged?.();
                    }}>
                    {v}{menu.node.status === k ? " ✓" : ""}
                  </button>
                ))}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
