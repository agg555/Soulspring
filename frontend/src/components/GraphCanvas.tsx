import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { GraphEdge, GraphNode, Suggestion } from "../types";
import { uiPrompt } from "./uiConfirm";
import {
  hierarchicalLayout, statusLaneLayout, type Pt,
} from "../graphLayout";
import { GRID, nodeById, sideAnchors } from "../graphCanvasLayout";
import { GraphEdgeLayer, GraphLegend, GraphNodeLayer } from "./graph/GraphCanvasParts";
import GraphCanvasToolbar from "./graph/GraphCanvasToolbar";
import { EdgeMenu, LinkFormDialog, NodeMenu } from "./graph/GraphCanvasMenus";
import GraphSideDrawer from "./graph/GraphSideDrawer";

/**
 * 统一图谱引擎(第四批 A,任务词 2026-09-01):
 * - 方框节点(圆角卡片:label + 可选 sub_label);连线 = 边缘锚点间曲线,类别色+标签;
 * - 画布交互:空白拖动平移 / 滚轮缩放 / 节点拖动(位置落库持久化);
 * - 网格吸附(20px,板级开关);拖动靠近其他节点边缘锚点热区高亮,松手自动建边;
 * - 边中点控制点:加派生节点 / 改标签 / 改类别 / 删除;同一对节点允许多条线;
 * - 自研薄实现(pointer events + state;开源参考按任务词口径:成熟算法自研即可);
 * - 侧栏:节点/边详情(人可改)+ ChatPanel(graph_node/graph_edge),板级对话(graph_board);
 *   AI 改动走 graph_field 轻档 / graph_add 批准闸门,无直改。
 *
 * 大文件拆分批(2026-09-10,纯移动零行为变化):几何/配色/卡型纯件→../graphCanvasLayout;
 * 边层/节点层/图例→./graph/GraphCanvasParts;浮层→./graph/GraphCanvasMenus;
 * 侧栏抽屉→./graph/GraphSideDrawer。本文件只留画布编排:状态 + 指针交互 + 落库。
 */
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
  // 批次三③体感:节点右键菜单(详情/改标签/删除,免翻侧栏)
  const [nodeMenu, setNodeMenu] = useState<{ nid: string; sx: number; sy: number } | null>(null);
  const [linkForm, setLinkForm] = useState<{ from: string; to: string } | null>(null);
  const [linkLabel, setLinkLabel] = useState("");
  const [linkKind, setLinkKind] = useState("自由");
  const [genCat, setGenCat] = useState("");
  const [nodeLabel, setNodeLabel] = useState("");
  const [kindOff, setKindOff] = useState<string[]>([]);   // 图例过滤(沿用第三批)
  const [chapterCap, setChapterCap] = useState<number | null>(null);  // 人物板:关系截至章
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

  const toGraph = (clientX: number, clientY: number): Pt => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: (clientX - rect.left - pan.x) / zoom, y: (clientY - rect.top - pan.y) / zoom };
  };
  // ── 指针交互 ──
  const onNodeDown = (e: React.PointerEvent, n: GraphNode) => {
    if (e.button !== 0) { e.preventDefault(); return; } // 仅左键拖节点(速赢④:中键 autoscroll 曾致画布飞走)
    e.stopPropagation();
    setSelected({ type: "node", id: n.id });
    setEdgeMenu(null);
    setNodeMenu(null);
    const gp = toGraph(e.clientX, e.clientY);
    drag.current = { nid: n.id, off: { x: gp.x - n.x, y: gp.y - n.y } };
    document.body.classList.add("graph-dragging");   // 批次三③:拖拽中抽屉半透明避让
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  const onCanvasDown = (e: React.PointerEvent) => {
    if (e.button !== 0) { e.preventDefault(); return; } // 仅左键平移;中键默认 autoscroll 会劫持坐标(速赢④)
    setSelected(null);
    setEdgeMenu(null);
    setNodeMenu(null);
    panRef.current = { sx: e.clientX, sy: e.clientY, pan: { ...pan } };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  const onMove = (e: React.PointerEvent) => {
    if (drag.current) {
      const gp = toGraph(e.clientX, e.clientY);
      const n = nodeById(nodes, drag.current.nid);
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
      const n = nodeById(nodes, drag.current.nid);
      const target = hot.current;
      drag.current = null;
      document.body.classList.remove("graph-dragging");
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

  // F1(批次二速赢 2026-09-05):导出 PNG——CSS 变量替换为实色后序列化 svg→canvas
  const exportPng = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    const cs = getComputedStyle(document.documentElement);
    const vars = ["--bg", "--panel", "--border", "--text", "--muted", "--accent"];
    let out = new XMLSerializer().serializeToString(clone);
    for (const v of vars) out = out.split(`var(${v})`).join(cs.getPropertyValue(v) || "#000");
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = img.width || 1600;
      canvas.height = img.height || 900;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = cs.getPropertyValue("--bg") || "#14161a";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      const a = document.createElement("a");
      a.download = `${board?.name ?? "graph"}.png`;
      a.href = canvas.toDataURL("image/png");
      a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(out);
  };


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

  const [newCard, setNewCard] = useState<"text" | "checklist">("text");

  const addFreeNode = async () => {
    if (!nodeLabel.trim()) return;
    try {
      // 放到当前视口中心(世界坐标)
      const rect = svgRef.current?.getBoundingClientRect();
      const cx = rect ? (rect.width / 2 - pan.x) / zoom : 200;
      const cy = rect ? (rect.height / 2 - pan.y) / zoom : 200;
      const nn = await api.createGraphNode(boardId, {
        label: nodeLabel.trim(), ref_type: "free",
        x: Math.round(cx / GRID) * GRID, y: Math.round(cy / GRID) * GRID,
      });
      if (newCard === "checklist") {
        await api.patchGraphNode(nn.node.id, {
          style: { card: "checklist", items: [] },
        });
      }
      setNodeLabel("");
      flash("节点已加");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  // 批次三④:清单卡模板一键生成(降空白成本,执行书 §2④)
  const addTemplate = async (title: string, items: string[]) => {
    try {
      const rect = svgRef.current?.getBoundingClientRect();
      const cx = rect ? (rect.width / 2 - pan.x) / zoom : 200;
      const cy = rect ? (rect.height / 2 - pan.y) / zoom : 200;
      const nn = await api.createGraphNode(boardId, {
        label: title, ref_type: "free",
        x: Math.round(cx / GRID) * GRID, y: Math.round(cy / GRID) * GRID,
      });
      await api.patchGraphNode(nn.node.id, {
        style: { card: "checklist", items: items.map((t) => ({ text: t, done: false })) },
      });
      flash(`已生成模板「${title}」`);
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

  // 批次七⑥:整板存为我的模板(存→选→套闭环的「存」端;套用在图谱中心新建板时选)
  const saveAsTemplate = async () => {
    const name = await uiPrompt("模板名称(新建板时可套用)", board?.name ?? "");
    if (!name || !name.trim()) return;
    try {
      const r = await api.saveTemplate(name.trim(), boardId);
      flash(`已存为模板「${name.trim()}」(${r.node_count} 节点${r.edge_count ? `/ ${r.edge_count} 连线` : ""})`);
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
      const a = e && nodeById(nodes, e.from_node_id), b = e && nodeById(nodes, e.to_node_id);
      if (a && b) return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    }
    const nid = t.source_node_id ?? t.node_id;
    if (nid) {
      const n = nodeById(nodes, nid);
      if (n) return { x: n.x, y: n.y };
    }
    return null;
  };

  const addDerived = async (eid: string) => {
    const e = edges.find((x) => x.id === eid);
    const a = e && nodeById(nodes, e.from_node_id), b = e && nodeById(nodes, e.to_node_id);
    if (!e || !a || !b) return;
    try {
      const mid = { x: (a.x + b.x) / 2, y: Math.max(a.y, b.y) + 150 };
      // 派生节点命名带出处(体感 2026-09-06:"派生节点"这名字太笼统)
      const nn = await api.createGraphNode(boardId, {
        label: `${a.label}·派生`, ref_type: "free",
        x: Math.round(mid.x / GRID) * GRID, y: Math.round(mid.y / GRID) * GRID,
      });
      // 派生规格(用户手绘 IMG20260902221810+20260906202041):派生节点挂在边的
      // "相关节点"(中点)正下方垂直引出,原边保留;补 A→N、N→B 两段成链,
      // "源-派生-下一源"都导向下一节点(渲染视觉=原边下挂一个三角)。
      await api.createGraphEdge(boardId, {
        from_node_id: e.from_node_id, to_node_id: nn.node.id,
        label: e.label, kind: e.kind,
      });
      await api.createGraphEdge(boardId, {
        from_node_id: nn.node.id, to_node_id: e.to_node_id,
        label: e.label, kind: e.kind,
      });
      setEdgeMenu(null);
      flash("已派生:节点挂中点下方,原边保留,两端接入成链");
      load();
    } catch (e2: unknown) {
      setError(String((e2 as Error).message || e2));
    }
  };

  // 批次二:布局整理(算完逐点 PATCH x/y 落库)
  const applyLayout = async (mode: "hier" | "status") => {
    const pos = mode === "status" ? statusLaneLayout(nodes) : hierarchicalLayout(nodes, edges);
    for (const [id, pt] of pos) {
      await api.patchGraphNode(id, { x: pt.x, y: pt.y });
    }
    flash("已按布局整理并落库");
    load();
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

  // F2(批次二速赢 2026-09-05):双击节点改名
  const renameNode = async (n: GraphNode) => {
    const nl = await uiPrompt("节点名称", n.label);
    if (nl !== null && nl.trim() && nl !== n.label) {
      await api.patchGraphNode(n.id, { label: nl.trim() });
      flash("节点已改名");
      load();
    }
  };

  const openNodeMenu = (nid: string, sx: number, sy: number) => {
    setSelected({ type: "node", id: nid });
    setEdgeMenu(null);
    setNodeMenu({ nid, sx, sy });
  };

  const toggleKind = (k: string) => setKindOff((cur) =>
    cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]);

  const selNode = selected?.type === "node" ? nodeById(nodes, selected.id) : null;
  const selEdge = selected?.type === "edge" ? edges.find((x) => x.id === selected.id) : null;
  const edgeMenuEdge = edgeMenu ? edges.find((x) => x.id === edgeMenu.eid) : null;

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
        <button className="link" onClick={() => applyLayout("hier")}
          title="按 从属/衍生/承接/来源 边整理成层级树">层级整理</button>
        {board?.kind === "hook" && (
          <button className="link" onClick={() => applyLayout("status")}
            title="按 埋设/强化/回收 三列分泳道">状态分列</button>
        )}
        {board?.kind === "character" && (
          <span className="row" style={{ margin: 0 }}>
            <span className="muted small">关系只看到第</span>
            <input type="number" min={1} value={chapterCap ?? ""}
              placeholder="∞" style={{ width: 56 }}
              onChange={(e) => setChapterCap(e.target.value ? Number(e.target.value) : null)} />
            <span className="muted small">章(留空=全部;人物关系时间轴,拍板 B)</span>
          </span>
        )}
        <button className="link" onClick={() => setShowBoardChat(!showBoardChat)}>
          {showBoardChat ? "收起板级对话" : "整板 AI 对话"}
        </button>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <GraphCanvasToolbar
        board={board} nodeLabel={nodeLabel} onNodeLabelChange={setNodeLabel}
        onAddFreeNode={addFreeNode} newCard={newCard} onNewCardChange={setNewCard}
        onAddTemplate={addTemplate} onSaveAsTemplate={saveAsTemplate}
        genCat={genCat} onGenCatChange={setGenCat} onGenerate={generate} />
      <GraphLegend nodes={nodes} edges={edges} kindOff={kindOff} onToggleKind={toggleKind} />

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
          <GraphEdgeLayer
            nodes={nodes} edges={edges} kindOff={kindOff} chapterCap={chapterCap}
            zoom={zoom} pan={pan} selected={selected}
            onSelectEdge={(eid) => setSelected({ type: "edge", id: eid })}
            onOpenMenu={(eid, sx, sy) => setEdgeMenu({ eid, sx, sy })} />
          <GraphNodeLayer
            nodes={nodes} boardKind={board?.kind} hotNode={hotNode} selected={selected}
            onNodeDown={onNodeDown} onNodeMenu={openNodeMenu} onRename={renameNode} />
        </g>
      </svg>
      <div className="graph-zoombar">
        <button title="放大" onClick={() => zoomBy(1.25)}>＋</button>
        <button title="缩小" onClick={() => zoomBy(1 / 1.25)}>－</button>
        <button title="重置 1:1" onClick={resetView}>1:1</button>
        <button title="导出 PNG" onClick={() => exportPng()}>⬇</button>
      </div>
      </div>

      {/* A4 自动连线小表单 */}
      {linkForm && (
        <LinkFormDialog
          fromLabel={nodeById(nodes, linkForm.from)?.label}
          toLabel={nodeById(nodes, linkForm.to)?.label}
          label={linkLabel} kind={linkKind}
          onLabelChange={setLinkLabel} onKindChange={setLinkKind}
          onConfirm={confirmLink} onCancel={() => setLinkForm(null)} />
      )}

      {/* A5 边中点菜单 */}
      {edgeMenu && edgeMenuEdge && (
        <EdgeMenu edge={edgeMenuEdge} sx={edgeMenu.sx} sy={edgeMenu.sy}
          onDerive={() => addDerived(edgeMenu.eid)}
          onChanged={() => { load(); setEdgeMenu(null); }}
          onError={(m) => setError(m)}
          onClose={() => setEdgeMenu(null)} />
      )}

      {nodeMenu && (() => {
        const mn = nodeById(nodes, nodeMenu.nid);
        if (!mn) return null;
        return (
          <NodeMenu node={mn} sx={nodeMenu.sx} sy={nodeMenu.sy}
            onOpenDetail={() => { setSelected({ type: "node", id: mn.id }); setNodeMenu(null); }}
            onOpenLink={(ref) => { onShowLinks?.(ref.etype, ref.id, ref.title); setNodeMenu(null); }}
            onChanged={() => { load(); setNodeMenu(null); }}
            onDeleted={() => { setSelected(null); load(); }}
            onError={(m) => setError(m)}
            onClose={() => setNodeMenu(null)} />
        );
      })()}

      {/* 侧栏:选中节点/边详情 + 对话;板级对话 */}
      {(selNode || selEdge || showBoardChat) && (
        <GraphSideDrawer
          board={board} boardId={boardId}
          selNode={selNode ?? null} selEdge={selEdge ?? null}
          showBoardChat={showBoardChat}
          onClose={() => { setSelected(null); setShowBoardChat(false); }}
          onDeleted={() => { setSelected(null); load(); }}
          reload={load}
          onShowLinks={onShowLinks}
          getAdoptBefore={getAdoptBefore}
          getAdoptAnchor={getAdoptAnchor} />
      )}
    </div>
  );
}
