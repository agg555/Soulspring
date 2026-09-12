import { useEffect, useState } from "react";
import { api } from "../api";

/**
 * 阅读模式(候选清单落地批 B):全屏连续阅读视图——章按创建序连排,
 * 无编辑控件;可切换 全部章节 / 仅定稿。Esc 或按钮退出。
 */
const STATUS_LABEL: Record<string, string> = {
  unwritten: "未写", draft: "草稿", human_editing: "人改中",
  final_review: "待终审", finalized: "定稿",
};

export default function ReadingMode({ pid, onClose }: {
  pid: string;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<"all" | "finalized">("all");
  const [bookName, setBookName] = useState("");
  const [chapters, setChapters] = useState<{ id: string; title: string;
    status: string; content: string }[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.reading(pid, mode).then((r) => {
      setBookName(r.book_name);
      setChapters(r.chapters);
    }).catch((e) => setError(String((e as Error).message || e)));
  }, [pid, mode]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 80, background: "var(--bg)",
      overflow: "auto" }}>
      <div style={{ position: "sticky", top: 0, background: "var(--bg)",
        borderBottom: "1px solid var(--border)", padding: "10px 18px", zIndex: 2 }}
        className="row spread">
        <b>📖 {bookName} · 阅读模式({chapters?.length ?? "…"} 章)</b>
        <span className="row" style={{ margin: 0 }}>
          <button className={mode === "all" ? "active" : ""}
            onClick={() => setMode("all")}>全部章节</button>
          <button className={mode === "finalized" ? "active" : ""}
            onClick={() => setMode("finalized")}>仅定稿</button>
          <button onClick={onClose}>退出(Esc)</button>
        </span>
      </div>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "18px 16px 80px" }}>
        {error && <p className="error">{error}</p>}
        {!chapters && <p className="muted">加载中…</p>}
        {chapters?.length === 0 && (
          <p className="muted">{mode === "finalized"
            ? "还没有定稿章;先在工作台走完状态机,或切到「全部章节」。"
            : "还没有带正文的章。"}</p>
        )}
        {chapters?.map((c) => (
          <article key={c.id} style={{ marginBottom: 42 }}>
            <h2 style={{ marginBottom: 4 }}>{c.title}</h2>
            <p className="muted small" style={{ margin: "0 0 12px" }}>
              {STATUS_LABEL[c.status] ?? c.status}
            </p>
            {c.content.split(/\n+/).map((para, i) => (
              <p key={i} style={{ fontSize: 16, lineHeight: 1.9,
                textIndent: "2em", margin: "0 0 10px" }}>{para}</p>
            ))}
          </article>
        ))}
      </div>
    </div>
  );
}
