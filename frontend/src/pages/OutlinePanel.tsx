import { useEffect, useState } from "react";
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
 */
const KIND_LABEL: Record<string, string> = {
  category: "总纲", volume: "卷", arc: "近纲", chapter: "章", scene: "场景",
};
// 每种节点可建的子类型(近纲可选:卷下既能建章也能建近纲)
const CHILD_KINDS: Record<string, string[]> = {
  category: ["volume"],
  volume: ["chapter", "arc"],
  arc: ["chapter"],
  chapter: ["scene"],
};
const STATUS_CLASS: Record<string, string> = {
  unwritten: "badge", draft: "badge warn", human_editing: "badge warn",
  final_review: "badge info", finalized: "badge ok",
};
const STATUS_LABEL: Record<string, string> = {
  unwritten: "未写", draft: "草稿", human_editing: "人改中",
  final_review: "待终审", finalized: "定稿",
};

interface TreeProps {
  nodes: OutlineNode[];
  pid: string;
  scenesEnabled: boolean;
  onChanged: () => void;
  onError: (m: string) => void;
  onOpenDrawer: (nid: string) => void;
  collapsed: Set<string>;                    // C6 展开记忆(localStorage 持久化)
  toggleCollapse: (id: string) => void;
  matchIds: Set<string> | null;              // C6 状态筛选命中集(null=不筛选)
}

function NodeRow({ node, depth, ctx }: { node: OutlineNode; depth: number; ctx: TreeProps }) {
  const { nodes, pid, scenesEnabled, onChanged, onError, onOpenDrawer } = ctx;
  const children = nodes.filter((n) => n.parent_id === node.id);
  const childKinds = (CHILD_KINDS[node.kind] ?? []).filter(
    (k) => k !== "scene" || scenesEnabled);
  const [adding, setAdding] = useState(false);
  const [newKind, setNewKind] = useState<string>(childKinds[0] ?? "");
  const [newTitle, setNewTitle] = useState("");
  const [log, setLog] = useState<StatusLogRow[] | null>(null);

  useEffect(() => {
    // 可建子类型随场景开关变化;当前选中类型不可建时回退到第一个
    if (!childKinds.includes(newKind)) setNewKind(childKinds[0] ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenesEnabled]);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      onChanged();
    } catch (e: unknown) {
      onError(String((e as Error).message || e));
    }
  };

  const kids = ctx.matchIds ? children.filter((c) => ctx.matchIds!.has(c.id)) : children;
  if (ctx.matchIds && !ctx.matchIds.has(node.id)) return null;
  const isCollapsed = ctx.collapsed.has(node.id);
  return (
    <li>
      <div className="tree-row" style={{ marginLeft: depth * 20 }}>
        {kids.length > 0 && (
          <button className="link" title={isCollapsed ? "展开" : "折叠"}
            onClick={() => ctx.toggleCollapse(node.id)}>{isCollapsed ? "▸" : "▾"}</button>
        )}
        <span className={`kind kind-${node.kind}`}>{KIND_LABEL[node.kind] ?? node.kind}</span>
        <b>
          <button className="link node-title-btn" title="打开节点详情抽屉"
            onClick={() => onOpenDrawer(node.id)}>{node.title}</button>
        </b>
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
                onChange={(e) => run(() => api.outlineStatus(node.id, e.target.value))}
              >
                <option value={node.status}>{node.status_label}</option>
                {node.allowed_transitions.map((s) => (
                  <option key={s} value={s}>{STATUS_LABEL[s] ?? s}</option>
                ))}
              </select>
              <button
                className="link"
                onClick={async () => {
                  const r = await api.outlineStatusLog(node.id);
                  setLog(r.log);
                }}
              >
                时间戳
              </button>
            </>
          )}
          {childKinds.length > 0 && (
            <button className="link" onClick={() => { setAdding(!adding); setNewTitle(""); }}>
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
            <select value={newKind} onChange={(e) => setNewKind(e.target.value)}>
              {childKinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          )}
          <input
            autoFocus
            placeholder={`新${KIND_LABEL[newKind]}标题`}
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <button
            onClick={() => {
              if (!newTitle.trim() || !newKind) return;
              run(() => api.outlineCreate(pid, { kind: newKind, parent_id: node.id, title: newTitle.trim() }));
              setAdding(false);
            }}
          >
            添加
          </button>
        </div>
      )}

      {log && (
        <div className="tree-row log-box" style={{ marginLeft: (depth + 1) * 20 }}>
          <div className="row spread">
            <b>状态变更时间戳(北极星 KPI 载体)</b>
            <button className="link" onClick={() => setLog(null)}>关闭</button>
          </div>
          {log.length === 0 && <p className="muted small">暂无变更记录。</p>}
          {log.map((l, i) => (
            <p key={i} className="small">
              {l.changed_at.replace("T", " ").slice(0, 19)} (UTC) ·{" "}
              {l.from_status ?? "—"} → {l.to_status}
            </p>
          ))}
        </div>
      )}

      {kids.length > 0 && !isCollapsed && (
        <ul className="tree-children">
          {kids.map((c) => (
            <NodeRow key={c.id} node={c} depth={depth + 1} ctx={ctx} />
          ))}
        </ul>
      )}
      {kids.length > 0 && isCollapsed && (
        <span className="muted small" style={{ marginLeft: (depth + 1) * 20 }}>
          (已折叠,{kids.length} 个子节点)
        </span>
      )}
    </li>
  );
}

export default function OutlinePanel({ pid, onGoPanel, onShowLinks }: {
  pid: string;
  onGoPanel?: (tab: "workbench" | "review") => void;
  onShowLinks?: (etype: string, nid: string, title: string) => void;   // B3 互链
}) {
  const [nodes, setNodes] = useState<OutlineNode[] | null>(null);
  const [scenesEnabled, setScenesEnabled] = useState(false);
  const [error, setError] = useState("");
  const [addingCat, setAddingCat] = useState(false);
  const [catTitle, setCatTitle] = useState("");
  const [drawerNid, setDrawerNid] = useState<string | null>(null);
  // C6 筛选/展开记忆 + 树/图双形态(骨架批执行书 §4,拍板 2ab;localStorage 持久化)
  const [form, setForm] = useState<"tree" | "graph">("tree");
  const [statusFilter, setStatusFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const load = () => {
    api.outline(pid).then((r) => setNodes(r.nodes)).catch((e) => setError(String(e.message || e)));
    api.settings().then((s) => setScenesEnabled(!!s.outline?.scenes_enabled)).catch(() => {});
  };
  useEffect(load, [pid]);
  useEffect(() => {
    try {
      setForm((localStorage.getItem(`outline:form:${pid}`) as "tree" | "graph") || "tree");
      setStatusFilter(localStorage.getItem(`outline:filter:${pid}`) ?? "");
      setCollapsed(new Set(JSON.parse(localStorage.getItem(`outline:collapsed:${pid}`) ?? "[]")));
    } catch { /* 记忆损坏时按默认 */ }
  }, [pid]);
  const toggleCollapse = (id: string) => setCollapsed((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    localStorage.setItem(`outline:collapsed:${pid}`, JSON.stringify([...next]));
    return next;
  });
  const setFormP = (f: "tree" | "graph") => { setForm(f); localStorage.setItem(`outline:form:${pid}`, f); };
  const setFilterP = (f: string) => { setStatusFilter(f); localStorage.setItem(`outline:filter:${pid}`, f); };

  if (error && !nodes) return <p className="error">{error}</p>;
  if (!nodes) return <p className="muted">加载中…</p>;

  // 场景显隐开关(C1):关闭时树与四级现状一致(数据仍在,只是不显示)
  const visible = scenesEnabled ? nodes : nodes.filter((n) => n.kind !== "scene");
  const roots = visible.filter((n) => n.parent_id === null);

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

  return (
    <div>
      <p className="muted small">
        层级:总纲 → 卷 → 近纲(可选,章可直接挂卷)→ 章 → 场景
        {scenesEnabled ? "(已开启)" : "(场景显隐关,设置页可开)"}。
        点节点标题打开详情抽屉;双击标题不再用于改名(改名在抽屉里)。
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
        {form === "tree" && (
          <>
            <button className="link" onClick={() => setCollapsed(new Set())}>全展开</button>
            <button className="link" onClick={() =>
              setCollapsed(new Set(visible
                .filter((n) => visible.some((c) => c.parent_id === n.id))
                .map((n) => n.id)))}>全折叠</button>
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
      {form === "tree" ? (
        <ul className="tree">
          {roots.map((n) => (
            <NodeRow key={n.id} node={n} depth={0} ctx={{
              nodes: visible, pid, scenesEnabled,
              onChanged: load, onError: setError,
              collapsed, toggleCollapse, matchIds,
              // A1(2026-09-01 拍板):点同一节点标题 = 关抽屉;点不同节点 = 切换
              onOpenDrawer: (nid) => setDrawerNid((cur) => (cur === nid ? null : nid)),
            }} />
          ))}
        </ul>
      ) : (
        <OutlineGraph nodes={visible} matchIds={matchIds}
          onOpen={(nid) => setDrawerNid((cur) => (cur === nid ? null : nid))} />
      )}
      {roots.length === 0 && <p className="muted">还没有总纲。点「+ 总纲」开始搭建大纲。</p>}

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
