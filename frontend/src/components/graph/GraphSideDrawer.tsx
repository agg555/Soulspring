/**
 * 图谱侧栏抽屉(大文件拆分批 2026-09-10 自 GraphCanvas.tsx 抽出;纯移动零行为变化):
 * 选中节点/边的详情表单 + 各挂 ChatPanel(graph_node/graph_edge/graph_board)+ 整板对话。
 * checkDraft 只在清单卡里用,故随抽屉搬来(局部状态,父组件无需知晓)。
 */
import { useState } from "react";
import { api } from "../../api";
import { cardOf, cardItems, EDGE_KINDS } from "../../graphCanvasLayout";
import { HOOK_STATUS_ORDER } from "../../graphLayout";
import type { GraphBoard, GraphEdge, GraphNode, Suggestion } from "../../types";
import ChatPanel from "../ChatPanel";
import { uiConfirm } from "../uiConfirm";

export default function GraphSideDrawer({
  board, boardId, selNode, selEdge, showBoardChat,
  onClose, onDeleted, reload, onShowLinks, getAdoptBefore, getAdoptAnchor,
}: {
  board: GraphBoard | null;
  boardId: string;
  selNode: GraphNode | null;
  selEdge: GraphEdge | null;
  showBoardChat: boolean;
  onClose: () => void;
  onDeleted: () => void;
  reload: () => void;
  onShowLinks?: (etype: string, nid: string, title: string) => void;
  getAdoptBefore: (s: Suggestion) => string;
  getAdoptAnchor: (sug: Suggestion) => { x: number; y: number } | null;
}) {
  const [checkDraft, setCheckDraft] = useState("");
  return (
    <div className="node-drawer">
      <div className="row spread">
        <b>{selNode ? "图谱节点" : selEdge ? "图谱连线" : `整板对话·${board?.name}`}</b>
        <button className="link" onClick={onClose}>关闭 ×</button>
      </div>
      {selNode && (
        <>
          <div className="row spread">
            <b>{selNode.label}</b>
            {onShowLinks && (
              <button className="link"
                onClick={() => onShowLinks("graph_node", selNode.id, selNode.label)}>
                🔗 关联
              </button>
            )}
          </div>
          <div className="form">
            <label>名称
              <input defaultValue={selNode.label} key={selNode.id + "l"}
                onBlur={(e) => e.target.value !== selNode.label &&
                  api.patchGraphNode(selNode.id, { label: e.target.value }).then(reload)} />
            </label>
            {board?.kind === "hook" && selNode && (
              <label>伏笔状态(埋设→强化→回收)
                <select
                  value={String((selNode.style as Record<string, unknown>)?.status ?? "埋设")}
                  onChange={(e2) => api.patchGraphNode(selNode.id, {
                    style: { ...((selNode.style as Record<string, unknown>) ?? {}),
                             status: e2.target.value },
                  }).then(reload)}>
                  {HOOK_STATUS_ORDER.map((st) => (
                    <option key={st} value={st}>{st}</option>
                  ))}
                </select>
              </label>
            )}
            {board?.kind === "free" && cardOf(selNode) === "checklist" && (() => {
              const items = cardItems(selNode);
              const done = items.filter((i) => i.done).length;
              const patchItems = (next: { text: string; done: boolean }[]) =>
                api.patchGraphNode(selNode.id, {
                  style: { ...((selNode.style as Record<string, unknown>) ?? {}), items: next },
                }).then(reload);
              return (
                <div className="form">
                  <b className="small">清单卡(已完成 {done}/{items.length})</b>
                  {items.map((it, i) => (
                    <label key={i} className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input type="checkbox" checked={!!it.done} onChange={() =>
                        patchItems(items.map((x, xi) => xi === i ? { ...x, done: !x.done } : x))} />
                      <span style={{ textDecoration: it.done ? "line-through" : undefined, flex: 1 }}>{it.text}</span>
                      <button className="link" onClick={() => patchItems(items.filter((_, xi) => xi !== i))}>✕</button>
                    </label>
                  ))}
                  <div className="row">
                    <input placeholder="加一条…" value={checkDraft}
                      onChange={(e) => setCheckDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && checkDraft.trim()) {
                          patchItems([...items, { text: checkDraft.trim(), done: false }]);
                          setCheckDraft("");
                        }
                      }} />
                    <button onClick={() => {
                      if (checkDraft.trim()) {
                        patchItems([...items, { text: checkDraft.trim(), done: false }]);
                        setCheckDraft("");
                      }
                    }}>加一条</button>
                  </div>
                </div>
              );
            })()}
            {board?.kind === "free" && cardOf(selNode) === "link" && (() => {
              const ref = ((selNode.style as Record<string, unknown>)?.ref) as
                { etype: string; id: string; title: string } | undefined;
              return ref ? (
                <p className="small">🔗 链接卡 → {ref.title}{" "}
                  <button className="link" onClick={() => onShowLinks?.(ref.etype, ref.id, ref.title)}>
                    打开关联抽屉</button></p>
              ) : (
                <p className="muted small">链接卡未绑定实体;可从关联抽屉点「📌 钉到自由板」。</p>
              );
            })()}
            <label>副标题
              <input defaultValue={selNode.sub_label ?? ""} key={selNode.id + "s"}
                onBlur={(e) => e.target.value !== (selNode.sub_label ?? "") &&
                  api.patchGraphNode(selNode.id, { sub_label: e.target.value }).then(reload)} />
            </label>
          </div>
          <div className="row">
            <button onClick={async () => {
              if (await uiConfirm(`删除节点「${selNode.label}」及其连线?`)) {
                api.deleteGraphNode(selNode.id).then(onDeleted);
              }
            }}>删除节点</button>
          </div>
          <ChatPanel
            projectId={board?.project_id ?? null}
            ownerType="graph_node"
            ownerId={selNode.id}
            defaultSessionName={`节点讨论·${selNode.label}`}
            allowPresets
            allowSkill
            allowRefs
            getAdoptBefore={getAdoptBefore}
            getAdoptAnchor={getAdoptAnchor}
            onAdopted={reload}
          />
        </>
      )}
      {selEdge && (
        <>
          {board?.kind === "character" && (
            <label>起于第几章(空=不标;人物关系时间轴)
              <input type="number" min={0} key={selEdge.id + "ac"}
                defaultValue={Number((selEdge.style as Record<string, unknown>)?.at_chapter) || ""}
                onBlur={(e2) => {
                  const v = e2.target.value ? Number(e2.target.value) : 0;
                  if (v !== Number((selEdge.style as Record<string, unknown>)?.at_chapter ?? 0)) {
                    api.patchGraphEdge(selEdge.id, {
                      style: { ...((selEdge.style as Record<string, unknown>) ?? {}),
                               at_chapter: v },
                    }).then(reload);
                  }
                }} />
            </label>
          )}
          <div className="form">
            <label>关系名
              <input defaultValue={selEdge.label} key={selEdge.id + "l"}
                onBlur={(e) => e.target.value !== selEdge.label &&
                  api.patchGraphEdge(selEdge.id, { label: e.target.value }).then(reload)} />
            </label>
            <label>类别
              <select value={selEdge.kind} key={selEdge.id + "k"}
                onChange={(e) => api.patchGraphEdge(selEdge.id, { kind: e.target.value }).then(reload)}>
                {EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}
              </select>
            </label>
          </div>
          <div className="row">
            <button onClick={async () => {
              if (await uiConfirm("删除这条连线?")) {
                api.deleteGraphEdge(selEdge.id).then(onDeleted);
              }
            }}>删除连线</button>
          </div>
          <ChatPanel
            projectId={board?.project_id ?? null}
            ownerType="graph_edge"
            ownerId={selEdge.id}
            defaultSessionName={`连线讨论`}
            allowPresets
            allowSkill
            allowRefs
            getAdoptBefore={getAdoptBefore}
            getAdoptAnchor={getAdoptAnchor}
            onAdopted={reload}
          />
        </>
      )}
      {showBoardChat && !selNode && !selEdge && (
        <ChatPanel
          projectId={board?.project_id ?? null}
          ownerType="graph_board"
          ownerId={boardId}
          defaultSessionName={`整板发散·${board?.name}`}
          allowPresets
          getAdoptAnchor={getAdoptAnchor}
          onAdopted={reload}
        />
      )}
    </div>
  );
}
