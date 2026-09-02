import { useEffect, useState } from "react";
import { api } from "../api";
import type { OutlineNode, StatusLogRow } from "../types";
import NodeDrawer from "../components/NodeDrawer";

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

  return (
    <li>
      <div className="tree-row" style={{ marginLeft: depth * 20 }}>
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
          <button className="link" onClick={() => { if (confirm(`删除「${node.title}」及其子节点(含挂在该节点上的会话/分支)?`)) run(() => api.outlineDelete(node.id)); }}>删</button>
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

      {children.length > 0 && (
        <ul className="tree-children">
          {children.map((c) => (
            <NodeRow key={c.id} node={c} depth={depth + 1} ctx={ctx} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function OutlinePanel({ pid, onGoPanel }: {
  pid: string;
  onGoPanel?: (tab: "workbench" | "review") => void;
}) {
  const [nodes, setNodes] = useState<OutlineNode[] | null>(null);
  const [scenesEnabled, setScenesEnabled] = useState(false);
  const [error, setError] = useState("");
  const [addingCat, setAddingCat] = useState(false);
  const [catTitle, setCatTitle] = useState("");
  const [drawerNid, setDrawerNid] = useState<string | null>(null);

  const load = () => {
    api.outline(pid).then((r) => setNodes(r.nodes)).catch((e) => setError(String(e.message || e)));
    api.settings().then((s) => setScenesEnabled(!!s.outline?.scenes_enabled)).catch(() => {});
  };
  useEffect(load, [pid]);

  if (error && !nodes) return <p className="error">{error}</p>;
  if (!nodes) return <p className="muted">加载中…</p>;

  // 场景显隐开关(C1):关闭时树与四级现状一致(数据仍在,只是不显示)
  const visible = scenesEnabled ? nodes : nodes.filter((n) => n.kind !== "scene");
  const roots = visible.filter((n) => n.parent_id === null);

  return (
    <div>
      <p className="muted small">
        层级:总纲 → 卷 → 近纲(可选,章可直接挂卷)→ 章 → 场景
        {scenesEnabled ? "(已开启)" : "(场景显隐关,设置页可开)"}。
        点节点标题打开详情抽屉;双击标题不再用于改名(改名在抽屉里)。
      </p>
      <div className="row">
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
      <ul className="tree">
        {roots.map((n) => (
          <NodeRow key={n.id} node={n} depth={0} ctx={{
            nodes: visible, pid, scenesEnabled,
            onChanged: load, onError: setError,
            // A1(2026-09-01 拍板):点同一节点标题 = 关抽屉;点不同节点 = 切换
            onOpenDrawer: (nid) => setDrawerNid((cur) => (cur === nid ? null : nid)),
          }} />
        ))}
      </ul>
      {roots.length === 0 && <p className="muted">还没有总纲。点「+ 总纲」开始搭建大纲。</p>}

      {drawerNid && (
        <NodeDrawer
          pid={pid}
          nid={drawerNid}
          onClose={() => setDrawerNid(null)}
          onChanged={load}
          onGoPanel={onGoPanel}
          onSwitch={setDrawerNid}
        />
      )}
    </div>
  );
}
