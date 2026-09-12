/**
 * 图谱画布浮层件(大文件拆分批 2026-09-10 自 GraphCanvas.tsx 抽出;纯移动零行为变化):
 * 自动连线小表单 / 边中点菜单 / 节点右键菜单。浮层只负责"长什么样、点了调谁",
 * 落库与状态更新仍由 GraphCanvas 的回调完成(与原内联实现逐句对应)。
 */
import { api } from "../../api";
import { EDGE_KINDS, cardOf } from "../../graphCanvasLayout";
import type { GraphEdge, GraphNode } from "../../types";
import { uiConfirm, uiPrompt } from "../uiConfirm";

export function LinkFormDialog({
  fromLabel, toLabel, label, kind, onLabelChange, onKindChange, onConfirm, onCancel,
}: {
  fromLabel: string | undefined;
  toLabel: string | undefined;
  label: string;
  kind: string;
  onLabelChange: (v: string) => void;
  onKindChange: (v: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="dialog" style={{ position: "fixed", right: 20, top: 90, zIndex: 80, width: 300 }}>
      <p><b>自动连线</b>:{fromLabel} → {toLabel}</p>
      <div className="row">
        <input placeholder="关系名(可空)" value={label}
          onChange={(e) => onLabelChange(e.target.value)} />
        <select value={kind} onChange={(e) => onKindChange(e.target.value)}>
          {EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}
        </select>
      </div>
      <div className="row">
        <button className="primary" onClick={onConfirm}>建立</button>
        <button onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

export function EdgeMenu({
  edge, sx, sy, onDerive, onChanged, onError, onClose,
}: {
  edge: GraphEdge;
  sx: number;
  sy: number;
  onDerive: () => void;
  onChanged: () => void;
  onError: (msg: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="graph-menu" style={{ left: sx + 12, top: sy + 8 }}>
      <button onClick={onDerive}>加派生节点</button>
      <button onClick={async () => {
        const label = await uiPrompt("新标签", edge.label);
        if (label !== null) api.patchGraphEdge(edge.id, { label })
          .then(onChanged).catch((e) => onError(String(e)));
      }}>改标签</button>
      <select value={edge.kind}
        onChange={(e) => api.patchGraphEdge(edge.id, { kind: e.target.value })
          .then(onChanged).catch((er) => onError(String(er)))}>
        {EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}
      </select>
      <button className="danger-link" onClick={() => {
        api.deleteGraphEdge(edge.id)
          .then(onChanged).catch((e) => onError(String(e)));
      }}>删除连线</button>
      <button className="link" onClick={onClose}>关闭</button>
    </div>
  );
}

export function NodeMenu({
  node, sx, sy, onOpenDetail, onOpenLink, onChanged, onDeleted, onError, onClose,
}: {
  node: GraphNode;
  sx: number;
  sy: number;
  onOpenDetail: () => void;
  onOpenLink: (ref: { etype: string; id: string; title: string }) => void;
  onChanged: () => void;
  onDeleted: () => void;
  onError: (msg: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="graph-menu" style={{ left: sx + 10, top: sy + 8 }}>
      <button onClick={onOpenDetail}>打开详情</button>
      {cardOf(node) === "link" && ((node.style as Record<string, unknown>)?.ref != null) && (
        <button onClick={() => {
          const ref = (node.style as Record<string, unknown>).ref as
            { etype: string; id: string; title: string };
          onOpenLink(ref);
        }}>🔗 打开关联抽屉</button>
      )}
      <button onClick={async () => {
        const label = await uiPrompt("新标签", node.label);
        if (label !== null) api.patchGraphNode(node.id, { label })
          .then(onChanged).catch((e) => onError(String(e)));
      }}>改标签</button>
      <button className="danger-link" onClick={async () => {
        if (await uiConfirm(`删除节点「${node.label}」及其连线?`)) api.deleteGraphNode(node.id)
          .then(onDeleted).catch((e) => onError(String(e)));
        onClose();
      }}>删除节点</button>
      <button className="link" onClick={onClose}>关闭</button>
    </div>
  );
}
