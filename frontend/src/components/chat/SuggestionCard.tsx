import type { Suggestion } from "../../types";

const SEVERITY_CLASS: Record<string, string> = {
  critical: "badge warn", major: "badge info", minor: "badge",
};
const TARGET_LABEL: Record<string, string> = {
  outline_field: "大纲字段", chapter_text: "正文修改", none: "仅提示",
  event_field: "事件字段", subtopic_add: "子题树",
};

/** 建议卡(大文件拆分批 2026-09-10 自 ChatPanel.tsx 抽出;纯移动零行为变化):
 * assistant 消息里的单条结构化建议渲染;采纳/直达/下钻行为经回调上抛。 */
export default function SuggestionCard({ s, canAdoptOutline, adopting, onBegin, onOpenNode, onDrill }: {
  s: Suggestion;
  canAdoptOutline: boolean;
  adopting: boolean;
  onBegin: () => void;
  onOpenNode?: (nid: string) => void;
  onDrill?: () => void;
}) {
  const adoptable = !s.adopted && s.target_type !== "none"
    && (s.target_type !== "outline_field" || canAdoptOutline);
  return (
    <div className={`sug-card${s.adopted ? " adopted" : ""}`}>
      <div className="entry-head">
        <span className={SEVERITY_CLASS[s.severity] ?? "badge"}>{s.severity}</span>
        <span className="badge">{TARGET_LABEL[s.target_type] ?? s.target_type}</span>
        {s.target_type === "outline_field" && s.target?.field && (
          <span className="badge">{s.target.field}</span>
        )}
        {s.adopted && <span className="badge ok">已采纳{s.adopt_summary ? ` · ${s.adopt_summary}` : ""}</span>}
      </div>
      {s.quote && <pre className="asm-content">「{s.quote}」</pre>}
      {s.issue && <p className="small">{s.issue}</p>}
      {s.suggestion && <p className="small ok">→ {s.suggestion}</p>}
      {adoptable && !adopting && <button className="link" onClick={onBegin}>采纳</button>}
      {onOpenNode && s.target?.node_id && (
        <button className="link" title="跳到大纲树并打开该节点抽屉"
          onClick={() => onOpenNode(String(s.target.node_id))}>📍节点</button>
      )}
      {onDrill && (
        <button className="link" title="下钻为构思树根节点并开专属子讨论(构思树三态收敛,采纳写回仍走闸门)"
          onClick={onDrill}>💭下钻</button>
      )}
    </div>
  );
}
