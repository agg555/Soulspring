import type { ChatMessage, GenTask, Suggestion } from "../../types";
import SuggestionCard from "./SuggestionCard";

/** 批次三③去太极客:UTC ISO → 本地"月-日 时:分"(对话 meta 默认只显本地时间)。 */
function fmtLocal(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.replace("T", " ").slice(0, 16);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 消息历史区(大文件拆分批 2026-09-10 自 ChatPanel.tsx 抽出;纯移动零行为变化):
 * user/assistant 消息流 + 建议卡 + 进行中任务指示。纯渲染,采纳/下钻/直达经回调上抛,
 * fmtLocal 只服务本区故随件安家。 */
export default function ChatHistory({
  messages, showEng, task, projectId, adopting, beginAdopt, onOpenNode, drillIdea,
}: {
  messages: ChatMessage[];
  showEng: boolean;
  task: GenTask | null;
  projectId: string | null;
  adopting: { msgId: string; idx: number } | null;
  beginAdopt: (m: ChatMessage, idx: number) => void;
  onOpenNode?: (nid: string) => void;
  drillIdea: (m: ChatMessage, idx: number, s: Suggestion) => void;
}) {
  return (
    <div className="chat-history">
      {messages.map((m) => (
        <div key={m.id} className={m.role === "user" ? "chat-msg user" : "chat-msg"}>
          <p className="muted small">
            {m.role === "user" ? "我" : "主编"}
            {" · "}{fmtLocal(m.created_at)}
            {showEng && m.role === "assistant" && m.meta?.model && `(${m.meta.model})`}
            {showEng && m.role === "assistant" && m.meta?.cost != null && ` · ¥${m.meta.cost.toFixed(4)}`}
            {showEng && m.role === "assistant" && m.meta?.cached_tokens != null && m.meta.request_tokens
              ? ` · 缓存命中 ${Math.round((m.meta.cached_tokens / m.meta.request_tokens) * 100)}%`
              : ""}
            {!showEng && m.role === "assistant" && (m.meta?.model || m.meta?.cost != null) && (
              <span style={{ cursor: "default" }}
                title={[m.meta?.model && `模型 ${m.meta.model}`,
                  m.meta?.cost != null && `成本 ¥${m.meta.cost.toFixed(4)}`,
                  m.meta?.cached_tokens != null && m.meta.request_tokens
                    && `缓存命中 ${Math.round((m.meta.cached_tokens / m.meta.request_tokens) * 100)}%`,
                  "开启「工程信息」可常显"].filter(Boolean).join(" · ")}> ⓘ</span>
            )}
          </p>
          {m.content && <pre>{m.content}</pre>}
          {/* 下限告警线(2026-09-09):回包低于配置下限时黄条提示(不拦截) */}
          {m.role === "assistant" && m.meta?.limit_warning && (
            <p className="badge warn" style={{ display: "block", margin: "4px 0" }}>
              ⚠ {String(m.meta.limit_warning)}
            </p>
          )}
          {m.role === "assistant" && m.meta?.parse_error && (
            <p className="muted small">ℹ 本轮为纯文本回复(未带结构化建议),不影响阅读;需要建议块可重发一次。</p>
          )}
          {(m.meta?.suggestions ?? []).map((s, i) => (
            <SuggestionCard
              key={i}
              s={s}
              canAdoptOutline={!!projectId}
              adopting={adopting?.msgId === m.id && adopting?.idx === i}
              onBegin={() => beginAdopt(m, i)}
              onOpenNode={onOpenNode}
              onDrill={projectId && !s.adopted ? () => drillIdea(m, i, s) : undefined}
            />
          ))}
        </div>
      ))}
      {task && task.status === "running" && (
        <p className="muted">
          ⟳ {({ context: "组装上下文", calling: "模型回包中", parsing: "解析建议中" } as Record<string, string>)[task.stage] ?? "生成中"}
          (可切页签,完成后顶部会有提示)…
        </p>
      )}
    </div>
  );
}
