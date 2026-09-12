import { useEffect, useState } from "react";
import { api } from "../api";
import type { OutlineNode } from "../types";
import OutlineGraph from "./OutlineGraph";
import NodeDrawer from "../components/NodeDrawer";

/**
 * 大纲画布(批次二,拍板 C=a+c 组合 2026-09-05)→ 批次五 v2(2026-09-06 用户
 * "大纲画布要像图谱一样移动调整/右键"):交互统一收编到 OutlineGraph 内建
 * (平移/缩放/节点拖动/右键菜单,位置 localStorage),本面板只做数据装载与抽屉,
 * 移除旧 scroll 平移+外层 scale(与内建双系打架,单一交互正本)。
 */
export default function OutlineCanvasPanel({ pid, onShowLinks }: {
  pid: string;
  onShowLinks?: (etype: string, nid: string, title: string) => void;
}) {
  const [nodes, setNodes] = useState<OutlineNode[] | null>(null);
  const [drawerNid, setDrawerNid] = useState<string | null>(null);
  // 批次五③:千章实测发现整树宽 15 万 px 不可导航——按卷过滤是千章可用的前提
  const [volFilter, setVolFilter] = useState("");
  const load = () => {
    api.outline(pid).then((r) => setNodes(r.nodes)).catch(() => setNodes([]));
  };
  useEffect(load, [pid]);

  if (!nodes) return <p className="muted">加载中…</p>;
  if (nodes.length === 0) return <p className="muted small">大纲还是空的——去左栏"大纲树"搭建。</p>;

  const volumes = nodes.filter((n) => n.kind === "volume" || n.kind === "arc");
  let shown = nodes;
  if (volFilter) {
    const keep = new Set([volFilter]);
    for (const n of nodes) {
      if (n.parent_id === volFilter || n.kind === "category") keep.add(n.id);
    }
    shown = nodes.filter((n) => keep.has(n.id));
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: 6 }}>
        <span className="muted small">空白拖拽平移 · 滚轮/＋－缩放 · 节点拖动调整(位置自动记住) · 右键菜单 · 点节点开抽屉</span>
        <select value={volFilter} style={{ margin: "0 0 0 auto" }}
          onChange={(e) => setVolFilter(e.target.value)}
          title="千章级整树过宽,按卷/近纲过滤后画布才可导航">
          <option value="">全部({nodes.length} 节点)</option>
          {volumes.map((v) => (
            <option key={v.id} value={v.id}>{v.title}(下含 {nodes.filter((n) => n.parent_id === v.id).length} 节点)</option>
          ))}
        </select>
      </div>
      <OutlineGraph pid={pid} nodes={shown} matchIds={null} editable onChanged={load}
        onOpen={(nid) => setDrawerNid((cur) => (cur === nid ? null : nid))} />
      {drawerNid && (
        <NodeDrawer pid={pid} nid={drawerNid}
          onClose={() => setDrawerNid(null)}
          onChanged={load}
          onShowLinks={onShowLinks} />
      )}
    </div>
  );
}
