import type { ChatMessage, OutlineNode, SubtopicItem, Suggestion } from "../../types";
import SubtopicTreeEditor from "../SubtopicTreeEditor";

/** 采纳批准闸门五弹窗(大文件拆分批 2026-09-10 自 ChatPanel.tsx 抽出;纯移动零行为变化):
 * graph_add(图谱新增)/ subtopic_add(子题树,人先增删改)/ graph_field /
 * outline_field+event_field(轻档 diff)/ chapter_text(重档进变更集)。
 * 纯渲染:确认/取消经 confirmAdopt 与 set 回调上抛,落库仍在 ChatPanel。 */
export default function ChatAdoptDialogs({
  adopting, adoptingMsg, adoptingSug, adoptItem, adoptingNode, adoptBeforeText,
  subtreeEdit, confirmAdopt, setAdopting, setSubtreeEdit,
}: {
  adopting: { msgId: string; idx: number } | null;
  adoptingMsg: ChatMessage | null | undefined;   // 原 find() 可 undefined,弹窗内以 ! 断言(与原内联一致)
  adoptingSug: Suggestion | null | undefined;
  adoptItem: {
    type?: string; label?: string; sub_label?: string;
    from_node_id?: string; to_node_id?: string; kind?: string;
  };
  adoptingNode: OutlineNode | null | undefined;
  adoptBeforeText: string;
  subtreeEdit: SubtopicItem[] | null;
  confirmAdopt: (m: ChatMessage, idx: number, _s: Suggestion) => Promise<void>;
  setAdopting: (v: { msgId: string; idx: number } | null) => void;
  setSubtreeEdit: (v: SubtopicItem[] | null) => void;
}) {
  return (
    <>
      {/* graph_add 批准闸门:预览将新增的节点/连线,人确认才落库(第四批 D) */}
      {adopting && adoptingSug && adoptingSug.target_type === "graph_add" && (
        <div className="dialog">
          <p><b>采纳新增建议(批准闸门)</b>:确认后将在图谱板新增:</p>
          {adoptItem.type === "node" && (
            <p className="small">
              方框节点:<b>{adoptItem.label}</b>
              {adoptItem.sub_label ? `(${adoptItem.sub_label})` : ""}
              —— 自动放到网格空位
            </p>
          )}
          {adoptItem.type === "edge" && (
            <p className="small">
              连线:{String(adoptItem.from_node_id ?? "").slice(0, 14)}…
              {" --["}{String(adoptItem.kind ?? "")}
              {adoptItem.label ? `·${String(adoptItem.label)}` : ""}{"]--> "}
              {String(adoptItem.to_node_id ?? "").slice(0, 14)}…
            </p>
          )}
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认新增
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
      {/* subtopic_add 批准闸门:AI 的子题树先经人增删改,批准才落库(WPS 大纲) */}
      {adopting && adoptingSug && adoptingSug.target_type === "subtopic_add" && (
        <div className="dialog">
          <p><b>采纳子题树建议(批准闸门)</b>:AI 建议在节点
            <b>{adoptingNode?.title ?? String(adoptingSug.target?.node_id ?? "?")}</b>
            下新增子题,可改标题/删项/加子级;批准后按下方现状落库。</p>
          <SubtopicTreeEditor
            tree={subtreeEdit ?? adoptingSug.target?.tree ?? []}
            onChange={setSubtreeEdit}
          />
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              批准落库
            </button>
            <button onClick={() => { setAdopting(null); setSubtreeEdit(null); }}>取消</button>
          </div>
        </div>
      )}
      {adopting && adoptingSug && adoptingSug.target_type === "graph_field" && (
        <div className="dialog">
          <p><b>采纳图谱字段建议(轻档)</b>:确认后写回并留痕。</p>
          <p className="small">字段:<b>{adoptingSug.target?.field}</b></p>
          <div className="diff-grid">
            <div>
              <p className="muted small">改前</p>
              <pre className="diff-pane">{adoptBeforeText || "(空)"}</pre>
            </div>
            <div>
              <p className="muted small">改后</p>
              <pre className="diff-pane">{adoptingSug.target?.value || "(空)"}</pre>
            </div>
          </div>
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认写回
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
      {/* 轻档采纳确认:改前/改后 diff → 人确认写回(A-采纳规则) */}
      {adopting && adoptingSug && (adoptingSug.target_type === "outline_field"
        || adoptingSug.target_type === "event_field") && (
        <div className="dialog">
          <p><b>采纳字段建议(轻档)</b>:确认后写回并留痕。</p>
          <p className="small">
            {adoptingSug.target_type === "outline_field" && (
              <>节点:<b>{adoptingNode?.title ?? adoptingSug.target?.node_id ?? "?"}</b> · </>
            )}
            字段:<b>{adoptingSug.target?.field}</b>
            {adoptingSug.target_type === "outline_field" && !adoptingNode && (
              <span className="muted">(节点信息加载中,或该节点不在本书大纲)</span>
            )}
          </p>
          <div className="diff-grid">
            <div>
              <p className="muted small">改前</p>
              <pre className="diff-pane">{adoptBeforeText || "(空)"}</pre>
            </div>
            <div>
              <p className="muted small">改后</p>
              <pre className="diff-pane">{adoptingSug.target?.value || "(空)"}</pre>
            </div>
          </div>
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认写回
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
      {adopting && adoptingSug && adoptingSug.target_type === "chapter_text" && (
        <div className="dialog">
          <p><b>采纳正文建议(重档)</b>:AI 的修改段落将作为新版本进入该章工作台变更集,
            在人改区核对后再合入,不会直接改正文。</p>
          <pre className="asm-content">{(adoptingSug.target?.revised_text || "").slice(0, 600)}
            {(adoptingSug.target?.revised_text || "").length > 600 ? "…" : ""}</pre>
          <div className="row">
            <button className="primary"
              onClick={() => adopting && confirmAdopt(adoptingMsg!, adopting.idx, adoptingSug)}>
              确认进变更集
            </button>
            <button onClick={() => setAdopting(null)}>取消</button>
          </div>
        </div>
      )}
    </>
  );
}
