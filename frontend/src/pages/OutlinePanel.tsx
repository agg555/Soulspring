import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { OutlineNode, StatusLogRow } from "../types";
import NodeDrawer from "../components/NodeDrawer";
import OutlineGraph from "./OutlineGraph";
import { uiConfirm } from "../components/uiConfirm";

/**
 * 大纲树(精修期第二批 C1 改造,执行书 2026-08-31):
 * 层级 = 总纲(原"大类")→ 卷 → 近纲(可选:章可直接挂卷)→ 章 → 场景(beat,开关开时)。
 * 点任意节点打开右侧详情抽屉(C2:字段编辑/状态机/节点对话/分支探索)。
 * settings.outline.scenes_enabled=false 时场景节点不显示(树与四级现状一致)。
 *
 * 超大流程二期①性能深化(2026-09-09,用户"优化卡顿非常重要"):
 * - 卡顿根因=每行 NodeRow 对全量节点 O(N) filter 找子级(2022 行=O(N²)≈400 万次
 *   比较/render)+默认全展开;修=childrenMap 一次建表 O(1) 查找 + NodeRow memo
 *   (ctx 稳定化后,无关状态变化不再全树重渲)+ 大书默认收起卷(章>120,localStorage
 *   记忆,展开才渲染子树;小书零配置不变)。
 * - 状态轮询降频核实:本面板无轮询(App 徽标 3s 轮询因 TABS 元素引用恒定被 React
 *   bailout 挡住,不波及本面板)——"降频"无对象,性能件落在 childrenMap+memo。
 */
const KIND_LABEL: Record<string, string> = {
  category: "总纲", volume: "卷", arc: "近纲", chapter: "章", scene: "场景", topic: "子题",
};
// 每种节点可建的子类型(近纲可选:卷下既能建章也能建近纲;
// topic=WPS 式子题:卷/近纲/章/子题下均可挂,可无限嵌套)
const CHILD_KINDS: Record<string, string[]> = {
  category: ["volume"],
  volume: ["chapter", "arc", "topic"],
  arc: ["chapter", "topic"],
  chapter: ["scene", "topic"],
  topic: ["topic"],
};
const STATUS_CLASS: Record<string, string> = {
  unwritten: "badge", draft: "badge warn", human_editing: "badge warn",
  final_review: "badge info", finalized: "badge ok",
};
const STATUS_LABEL: Record<string, string> = {
  unwritten: "未写", draft: "草稿", human_editing: "人改中",
  final_review: "待终审", finalized: "定稿",
};
const BIG_BOOK_CHAPTERS = 120;   // 章数超过此值默认收起卷(小书零配置不变)

interface TreeProps {
  pid: string;
  scenesEnabled: boolean;
  onChanged: () => void;
  onError: (m: string) => void;
  onOpenDrawer: (nid: string) => void;
  onRowMenu?: (m: { id: string; title: string; kind: string; sx: number; sy: number }) => void;
  collapsed: Set<string>;                    // C6 展开记忆(localStorage 持久化)
  toggleCollapse: (id: string) => void;
  matchIds: Set<string> | null;              // C6 状态筛选命中集(null=不筛选)
  childrenMap: Map<string, OutlineNode[]>;   // 二期①:父→子一次建表,O(1) 查找
  adding: AddingState | null;                // 二期①:行内加子表单态(面板层集中)
  onAddingChange: (a: AddingState | null) => void;
  logNid: string | null;                     // 二期①:时间戳查看行(一次一行)
  logData: StatusLogRow[] | null;
  onShowLog: (nid: string | null, prev: string | null) => void;
}

// 加子节点行内表单态(面板层集中管理:同一时刻只有一行在加,行保持纯渲染——
// 二期①性能件:千行展开时省掉每行 5 个 hooks 的挂载开销)
interface AddingState { nid: string; kind: string; title: string }

const NodeRow = memo(function NodeRow({ node, depth, ctx }: {
  node: OutlineNode; depth: number; ctx: TreeProps;
}) {
  const { pid, scenesEnabled, onChanged, onError, onOpenDrawer } = ctx;
  const children = ctx.childrenMap.get(node.id) ?? [];
  const childKinds = (CHILD_KINDS[node.kind] ?? []).filter(
    (k) => k !== "scene" || scenesEnabled);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      onChanged();
    } catch (e: unknown) {
      onError(String((e as Error).message || e));
    }
  };

  const adding = ctx.adding?.nid === node.id ? ctx.adding : null;
  const kids = ctx.matchIds ? children.filter((c) => ctx.matchIds!.has(c.id)) : children;
  if (ctx.matchIds && !ctx.matchIds.has(node.id)) return null;
  const isCollapsed = ctx.collapsed.has(node.id);
  const showLog = ctx.logNid === node.id;   // 时间戳查看一次一行(状态在面板层)
  return (
    <li>
      <div className="tree-row" style={{ marginLeft: depth * 20 }}>
        {kids.length > 0 && (
          <button className="link" title={isCollapsed ? "展开" : "折叠"}
            onClick={() => ctx.toggleCollapse(node.id)}>{isCollapsed ? "▸" : "▾"}</button>
        )}
        <span className={`kind kind-${node.kind}`}>{KIND_LABEL[node.kind] ?? node.kind}</span>
        <b>
          <button className="link node-title-btn" title={node.body
            ? `${node.body.slice(0, 100)}${node.body.length > 100 ? "…" : ""}(点开详情抽屉)`
            : "打开节点详情抽屉(右键=快捷菜单)"}
            onContextMenu={(e) => {
              // 批次三⑥对齐:大纲树行右键菜单(图谱右键同款交互;详情/加子/删除)
              e.preventDefault();
              ctx.onRowMenu?.({ id: node.id, title: node.title, kind: node.kind,
                sx: e.clientX, sy: e.clientY });
            }}
            onClick={() => onOpenDrawer(node.id)}>{node.title}</button>
        </b>
        {node.body && (
          <span className="muted small" title={
            `悬浮预览:${node.body.slice(0, 100)}${node.body.length > 100 ? "…" : ""}`}>
            ▤
          </span>
        )}
        {node.kind === "scene" && node.scene_fields?.target_words && (
          <span className="badge" title="场景目标/预计字数">
            {node.scene_fields.goal ? `${node.scene_fields.goal.slice(0, 12)}·` : ""}
            {node.scene_fields.target_words}字
          </span>
        )}
        {node.kind === "chapter" && (
          <span className={STATUS_CLASS[node.status]}>{node.status_label}</span>
        )}
        <span className="tree-actions">
          {node.kind === "chapter" && (
            <>
              <select
                value={node.status}
                onChange={async (e) => {
                  // 二期②:定稿解封=罕见操作,二次确认(取消则把下拉拨回原值)
                  if (node.status === "finalized" &&
                      !(await uiConfirm(`「${node.title}」已定稿,解封回「${STATUS_LABEL[e.target.value] ?? e.target.value}」?`))) {
                    e.currentTarget.value = node.status;
                    return;
                  }
                  run(() => api.outlineStatus(node.id, e.target.value));
                }}
              >
                <option value={node.status}>{node.status_label}</option>
                {node.allowed_transitions.map((s) => (
                  <option key={s} value={s}>{STATUS_LABEL[s] ?? s}</option>
                ))}
              </select>
              <button
                className="link"
                onClick={() => ctx.onShowLog(node.id, showLog ? null : node.id)}
              >
                时间戳
              </button>
            </>
          )}
          {childKinds.length > 0 && (
            <button className="link" onClick={() =>
              ctx.onAddingChange(adding ? null : { nid: node.id, kind: childKinds[0] ?? "", title: "" })}>
              +{childKinds.map((k) => KIND_LABEL[k]).join("/")}
            </button>
          )}
          <button className="link" onClick={() => run(() => api.outlineMove(node.id, "up"))}>↑</button>
          <button className="link" onClick={() => run(() => api.outlineMove(node.id, "down"))}>↓</button>
          <button className="link" onClick={async () => { if (await uiConfirm(`删除「${node.title}」及其子节点(含挂在该节点上的会话/分支)?`)) run(() => api.outlineDelete(node.id)); }}>删</button>
        </span>
      </div>

      {adding && childKinds.length > 0 && (
        <div className="tree-row" style={{ marginLeft: (depth + 1) * 20 }}>
          {childKinds.length > 1 && (
            <select value={adding.kind} onChange={(e) =>
              ctx.onAddingChange({ ...adding, kind: e.target.value })}>
              {childKinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          )}
          <input
            autoFocus
            placeholder={`新${KIND_LABEL[adding.kind]}标题`}
            value={adding.title}
            onChange={(e) => ctx.onAddingChange({ ...adding, title: e.target.value })}
          />
          <button
            onClick={() => {
              if (!adding.title.trim() || !adding.kind) return;
              run(() => api.outlineCreate(pid, { kind: adding.kind, parent_id: node.id, title: adding.title.trim() }));
              ctx.onAddingChange(null);
            }}
          >
            添加
          </button>
        </div>
      )}

      {showLog && ctx.logData && (
        <div className="tree-row log-box" style={{ marginLeft: (depth + 1) * 20 }}>
          <div className="row spread">
            <b>状态变更时间戳(北极星 KPI 载体)</b>
            <button className="link" onClick={() => ctx.onShowLog(node.id, null)}>关闭</button>
          </div>
          {ctx.logData.length === 0 && <p className="muted small">暂无变更记录。</p>}
          {ctx.logData.map((l, i) => (
            <p key={i} className="small">
              {l.changed_at.replace("T", " ").slice(0, 19)} (UTC) ·{" "}
              {l.from_status ?? "—"} → {l.to_status}
            </p>
          ))}
        </div>
      )}

      {kids.length > 0 && !isCollapsed && (
        kids.length > CHUNK_SIZE
          ? <ChunkedChildren kids={kids} depth={depth} ctx={ctx} />
          : (
            <ul className="tree-children">
              {kids.map((c) => (
                <NodeRow key={c.id} node={c} depth={depth + 1} ctx={ctx} />
              ))}
            </ul>
          )
      )}
      {kids.length > 0 && isCollapsed && (
        <span className="muted small" style={{ marginLeft: (depth + 1) * 20 }}>
          (已折叠,{kids.length} 个子节点)
        </span>
      )}
    </li>
  );
});

// 二期补优(用户实测"1000 子节点展开还是有点卡"):childrenMap+memo 治的是重渲,
// 剩下的首挂成本=React 一次性 mount 上千个组件。此处按帧分批续挂(首帧 60 行,
// 每帧 +120),配 content-visibility,展开手感=即点即开,余量后台静默补齐。
const CHUNK_SIZE = 60;
const CHUNK_STEP = 120;

function ChunkedChildren({ kids, depth, ctx }: {
  kids: OutlineNode[]; depth: number; ctx: TreeProps;
}) {
  const [count, setCount] = useState(Math.min(kids.length, CHUNK_SIZE));
  useEffect(() => {
    setCount((c) => Math.min(c, kids.length));   // 子级缩减(删章)时收拢
  }, [kids.length]);
  useEffect(() => {
    if (count >= kids.length) return;
    let raf = 0;
    const t = setTimeout(() => {
      raf = requestAnimationFrame(() =>
        setCount((c) => Math.min(c + CHUNK_STEP, kids.length)));
    }, 16);
    return () => { clearTimeout(t); cancelAnimationFrame(raf); };
  }, [count, kids.length]);
  return (
    <ul className="tree-children">
      {kids.slice(0, count).map((c) => (
        <NodeRow key={c.id} node={c} depth={depth + 1} ctx={ctx} />
      ))}
      {count < kids.length && (
        <li className="muted small" style={{ marginLeft: (depth + 1) * 20 }}>
          正在载入其余 {kids.length - count} 章…
        </li>
      )}
    </ul>
  );
}

export default function OutlinePanel({ pid, onGoPanel, onShowLinks, onAskAI, openNodeId }: {
  pid: string;
  onGoPanel?: (tab: "workbench" | "review") => void;
  onShowLinks?: (etype: string, nid: string, title: string) => void;   // B3 互链
  onAskAI?: (preset: string) => void;   // 批次二:树层 AI(体检)直跳书级对话
  openNodeId?: string | null;           // 外部直达抽屉(建议块"📍节点")
}) {

  const [nodes, setNodes] = useState<OutlineNode[] | null>(null);
  const [scenesEnabled, setScenesEnabled] = useState(false);
  const [error, setError] = useState("");
  const [addingCat, setAddingCat] = useState(false);
  const [catTitle, setCatTitle] = useState("");
  const [drawerNid, setDrawerNid] = useState<string | null>(null);
  // 批次三②:算法体检(免费常驻,零 LLM;与 🤖AI 体检=深度可选 并存)
  const [algo, setAlgo] = useState<null | {
    total_issues: number;
    checks: { key: string; title: string; count: number;
      items: { node_id: string; title: string; detail: string }[] }[];
  }>(null);
  const [algoBusy, setAlgoBusy] = useState(false);
  // 批次三⑥对齐:大纲树行右键菜单(图谱 graph-menu 复用样式)
  const [rowMenu, setRowMenu] = useState<{ id: string; title: string; kind: string;
    sx: number; sy: number } | null>(null);
  // 二期①:行内加子表单/时间戳查看态(面板层集中,行保持纯渲染;
  // 右键菜单"加子节点"直接落 adding 态并展开该行)
  const [adding, setAdding] = useState<AddingState | null>(null);
  const [logNid, setLogNid] = useState<string | null>(null);
  const [logData, setLogData] = useState<StatusLogRow[] | null>(null);
  // C6 筛选/展开记忆 + 树/图双形态(骨架批执行书 §4,拍板 2ab;localStorage 持久化)
  const [form, setForm] = useState<"tree" | "graph">("tree");
  const [statusFilter, setStatusFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  // 二期①:大书默认收起卷的"首次节点到达"决策标记(换书重置)
  const collapseInited = useRef(false);

  const onAddingChange = useCallback((a: AddingState | null) => setAdding(a), []);
  const onShowLog = useCallback((nid: string | null, prev: string | null) => {
    if (nid === null || prev !== null) { setLogNid(null); setLogData(null); return; }
    setLogNid(nid);
    api.outlineStatusLog(nid).then((r) => setLogData(r.log))
      .catch((e) => setError(String((e as Error).message || e)));
  }, []);

  const load = useCallback(() => {
    api.outline(pid).then((r) => {
      setNodes(r.nodes);
      // 二期①:大书默认收起卷(仅首次,有记忆尊重记忆;小书零配置不变)
      if (!collapseInited.current) {
        collapseInited.current = true;
        let stored: string[] | null = null;
        try {
          const raw = localStorage.getItem(`outline:collapsed:${pid}`);
          stored = raw ? JSON.parse(raw) : null;
        } catch { stored = null; }
        if (stored) {
          setCollapsed(new Set(stored));
        } else if (r.nodes.filter((n) => n.kind === "chapter").length > BIG_BOOK_CHAPTERS) {
          // 只收卷,总纲保持可见(与图谱形态默认一致;展开才渲染子树)
          setCollapsed(new Set(r.nodes.filter((n) => n.kind === "volume").map((n) => n.id)));
        }
      }
    }).catch((e) => setError(String(e.message || e)));
    api.settings().then((s) => setScenesEnabled(!!s.outline?.scenes_enabled)).catch(() => {});
  }, [pid]);
  useEffect(load, [pid]);
  useEffect(() => {   // 外部(建议块)直达:打开抽屉(同节点重复点击用 key 变化触发)
    if (openNodeId) setDrawerNid(openNodeId);
  }, [openNodeId]);

  useEffect(() => {
    try {
      setForm((localStorage.getItem(`outline:form:${pid}`) as "tree" | "graph") || "tree");
      setStatusFilter(localStorage.getItem(`outline:filter:${pid}`) ?? "");
    } catch { /* 记忆损坏时按默认 */ }
    collapseInited.current = false;   // 换书重置:下一批节点到来时重新决定默认收起
  }, [pid]);
  const toggleCollapse = useCallback((id: string) => setCollapsed((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    try { localStorage.setItem(`outline:collapsed:${pid}`, JSON.stringify([...next])); }
    catch { /* 存储不可用忽略,本会话折叠态仍在 */ }
    return next;
  }), [pid]);
  const setFormP = (f: "tree" | "graph") => { setForm(f); try { localStorage.setItem(`outline:form:${pid}`, f); } catch { /* 忽略 */ } };
  const setFilterP = (f: string) => { setStatusFilter(f); try { localStorage.setItem(`outline:filter:${pid}`, f); } catch { /* 忽略 */ } };

  // ── 全部 hooks 必须在提前返回之前(React #310 前科:Settings 页两次白屏)──
  const nodesList = nodes ?? [];
  // 场景显隐开关(C1):关闭时树与四级现状一致(数据仍在,只是不显示)
  const visible = scenesEnabled ? nodesList : nodesList.filter((n) => n.kind !== "scene");

  // C6 状态筛选:命中章 + 其祖先链 + 其后代(场景)保持树形可读
  let matchIds: Set<string> | null = null;
  if (statusFilter) {
    matchIds = new Set<string>();
    const byId = new Map(visible.map((n) => [n.id, n]));
    for (const m of visible) {
      if (m.kind !== "chapter" || m.status !== statusFilter) continue;
      matchIds.add(m.id);
      let cur = byId.get(m.parent_id ?? "");
      while (cur) { matchIds.add(cur.id); cur = byId.get(cur.parent_id ?? ""); }
      for (const d of visible) {
        let p = byId.get(d.parent_id ?? "");
        while (p) { if (p.id === m.id) { matchIds.add(d.id); break; } p = byId.get(p.parent_id ?? ""); }
      }
    }
  }

  // 二期①:父→子一次建表(NodeRow 不再每行 O(N) filter 全量节点)
  const childrenMap = useMemo(() => {
    const m = new Map<string, OutlineNode[]>();
    for (const n of visible) {
      const k = n.parent_id ?? "";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(n);
    }
    return m;
  }, [visible]);
  const roots = useMemo(() => childrenMap.get("") ?? [], [childrenMap]);

  // 二期①:ctx 稳定化(memo 生效前提)——数据/收叠/筛选/表单态不变则引用不变
  const onOpenDrawer = useCallback(
    (nid: string) => setDrawerNid((cur) => (cur === nid ? null : nid)), []);
  const ctx = useMemo<TreeProps>(() => ({
    pid, scenesEnabled,
    onChanged: load, onError: setError,
    collapsed, toggleCollapse, matchIds, childrenMap,
    // A1(2026-09-01 拍板):点同一节点标题 = 关抽屉;点不同节点 = 切换
    onOpenDrawer,
    onRowMenu: setRowMenu,
    adding, onAddingChange, logNid, logData, onShowLog,
  }), [pid, scenesEnabled, load, collapsed, toggleCollapse, matchIds,
    childrenMap, onOpenDrawer, adding, logNid, logData, onShowLog]);

  if (error && !nodes) return <p className="error">{error}</p>;
  if (!nodes) return <p className="muted">加载中…</p>;

  return (
    <div>
      <p className="muted small">
        层级:总纲 → 卷 → 近纲(可选,章可直接挂卷)→ 章 → 场景;卷/近纲/章下可挂
        「子题」,子题下还可挂子题(WPS 式标题分级)。
        点节点标题打开详情抽屉;悬浮标题可预览正文前 100 字。
      </p>
      <div className="row">
        <button className={form === "tree" ? "active" : ""}
          onClick={() => setFormP("tree")}>树形</button>
        <button className={form === "graph" ? "active" : ""}
          onClick={() => setFormP("graph")}>图谱</button>
        <select value={statusFilter} onChange={(e) => setFilterP(e.target.value)}>
          <option value="">状态:全部</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>状态:{v}</option>
          ))}
        </select>
        {onAskAI && (
          <button className="link" title="AI 检查大纲结构:断头章/孤立卷/密度/钩子"
            onClick={() => onAskAI("book_outline_review")}>🤖 AI 体检</button>
        )}
        <button className="link" disabled={algoBusy}
          title="六项纯规则检查,零成本常驻:断头章/孤立卷/章密度/伏笔未回收/重名/时间线冲突"
          onClick={() => {
            setAlgoBusy(true);
            api.algorithmCheck(pid)
              .then(setAlgo)
              .catch((e) => setError(String(e.message || e)))
              .finally(() => setAlgoBusy(false));
          }}>{algoBusy ? "⏳ 体检中" : "📋 算法体检(免费)"}</button>
        {form === "tree" && (
          <>
            <button className="link" onClick={() => {
              // 渐进展开(候选清单落地批 C,虚拟滚动务实实现):大书一次性
              // setCollapsed(空)=2000 行同帧全 mount(实测 3.2s 冻结);改为
              // 分帧逐层解折叠,首帧即响应,铺开过程不冻滚动/点击。
              const target = new Set<string>();
              const pending = visible
                .filter((n) => visible.some((c) => c.parent_id === n.id))
                .map((n) => n.id);
              if (pending.length <= 80) { setCollapsed(target); return; }
              let i = 0;
              const step = () => {
                const slice = pending.slice(i, i + 60);
                i += 60;
                if (slice.length === 0) { setCollapsed(target); return; }
                setCollapsed((cur) => {
                  const next = new Set(cur);
                  for (const id of slice) next.delete(id);
                  return next;
                });
                requestAnimationFrame(() => setTimeout(step, 16));
              };
              step();
            }}>全展开</button>
            <button className="link" title="WPS 目录模式:只看标题(全部折叠,悬浮标题可预览正文)"
              onClick={() =>
                setCollapsed(new Set(visible
                  .filter((n) => visible.some((c) => c.parent_id === n.id))
                  .map((n) => n.id)))}>目录(纯标题)</button>
          </>
        )}
        <button onClick={() => setAddingCat(!addingCat)}>+ 总纲</button>
        {addingCat && (
          <>
            <input
              autoFocus
              placeholder="总纲标题"
              value={catTitle}
              onChange={(e) => setCatTitle(e.target.value)}
            />
            <button
              onClick={() => {
                if (!catTitle.trim()) return;
                api.outlineCreate(pid, { kind: "category", parent_id: null, title: catTitle.trim() })
                  .then(() => { setAddingCat(false); setCatTitle(""); load(); })
                  .catch((e) => setError(String(e.message || e)));
              }}
            >
              添加
            </button>
          </>
        )}
        <span className="muted small">场景显隐:{scenesEnabled ? "开" : "关"}(设置页切换)</span>
      </div>
      {algo && (
        <div className="algo-panel">
          <h4>
            📋 算法体检
            <span className={algo.total_issues ? "badge warn" : "badge ok"}>
              {algo.total_issues ? `${algo.total_issues} 项待处理` : "全部健康"}
            </span>
            <span style={{ flex: 1 }} />
            <button className="link" onClick={() => setAlgo(null)}>关闭</button>
          </h4>
          {algo.checks.map((c) => (
            <div className="algo-check" key={c.key}>
              <div className="algo-check-title">
                <b>{c.title}</b>
                <span className={c.count ? "badge warn" : "ok"}>
                  {c.count ? `${c.count} 项` : "✓ 通过"}
                </span>
              </div>
              {c.items.map((it) => (
                <div className="algo-item" key={it.node_id}>
                  <b>{it.title}</b> — {it.detail}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {form === "tree" ? (
        <ul className="tree">
          {roots.map((n) => (
            <NodeRow key={n.id} node={n} depth={0} ctx={ctx} />
          ))}
        </ul>
      ) : (
        <OutlineGraph pid={pid} nodes={visible} matchIds={matchIds} editable onChanged={load}
          onOpen={(nid) => setDrawerNid((cur) => (cur === nid ? null : nid))} />
      )}
      {roots.length === 0 && <p className="muted">还没有总纲。点「+ 总纲」开始搭建大纲。</p>}

      {rowMenu && (
        <div className="graph-menu" style={{ left: rowMenu.sx + 8, top: rowMenu.sy + 6 }}>
          <b className="small" style={{ padding: "0 8px" }}>
            {KIND_LABEL[rowMenu.kind] ?? rowMenu.kind}·{rowMenu.title.slice(0, 10)}</b>
          <button onClick={() => { setDrawerNid(rowMenu.id); setRowMenu(null); }}>打开详情</button>
          {(CHILD_KINDS[rowMenu.kind] ?? []).some((k) => k !== "scene" || scenesEnabled) && (
            <button onClick={() => {
              // 加子节点:面板层表单态直接落位,并展开该行(折叠态下表单不可见)
              const kinds = (CHILD_KINDS[rowMenu.kind] ?? []).filter((k) => k !== "scene" || scenesEnabled);
              setAdding({ nid: rowMenu.id, kind: kinds[0] ?? "chapter", title: "" });
              setCollapsed((cur) => { const n = new Set(cur); n.delete(rowMenu.id); return n; });
              setRowMenu(null);
            }}>加子节点</button>
          )}
          <button onClick={() => { setDrawerNid(rowMenu.id); setRowMenu(null); }}>改名/字段</button>
          <button className="danger-link" onClick={async () => {
            if (await uiConfirm(`删除「${rowMenu.title}」及其子节点(含挂在该节点上的会话/分支)?`)) {
              try {
                await api.outlineDelete(rowMenu.id);
                load();
              } catch (e) { setError(String((e as Error).message || e)); }
            }
            setRowMenu(null);
          }}>删除节点</button>
          <button className="link" onClick={() => setRowMenu(null)}>关闭</button>
        </div>
      )}
      {drawerNid && (
        <NodeDrawer
          pid={pid}
          nid={drawerNid}
          onClose={() => setDrawerNid(null)}
          onChanged={load}
          onGoPanel={onGoPanel}
          onSwitch={setDrawerNid}
          onShowLinks={onShowLinks}
        />
      )}
    </div>
  );
}
