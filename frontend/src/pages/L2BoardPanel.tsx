import { useEffect, useState } from "react";
import { api } from "../api";
import type { OutlineNode } from "../types";

/**
 * L2 状态看板(F9/F10,7 页之一):
 * 回写草案审核(机器起草 diff → 人批准/驳回)+ 伏笔池看板(生命周期+烂尾告警)+ 真相文件浏览。
 */
export default function L2BoardPanel({ pid }: { pid: string }) {
  const [drafts, setDrafts] = useState<{ id: string; file_type: string; content: string; before: string; updated_at: string }[]>([]);
  const [hooks, setHooks] = useState<{ detail: string; planted_chapter: number; status: string; age: number; stale: boolean }[]>([]);
  const [curChapter, setCurChapter] = useState(0);
  const [staleThreshold, setStaleThreshold] = useState(15);
  const [finalChapters, setFinalChapters] = useState<OutlineNode[]>([]);
  const [redraftNid, setRedraftNid] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = () => {
    api.l2Drafts(pid).then((r) => setDrafts(r.drafts)).catch((e) => setError(String(e.message || e)));
    api.hookBoard(pid).then((r) => {
      setHooks(r.hooks);
      setCurChapter(r.current_chapter);
      setStaleThreshold(r.stale_threshold);
    }).catch((e) => setError(String(e.message || e)));
    api.outline(pid).then((r) => {
      const fin = r.nodes.filter((n) => n.kind === "chapter" && n.status === "finalized");
      setFinalChapters(fin);
      setRedraftNid((cur) => cur || fin[0]?.id || "");
    }).catch(() => {});
  };
  useEffect(load, [pid]);

  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 4000);
  };

  const approve = async (id: string) => {
    try {
      await api.l2Approve(id);
      flash("已批准,草案合并入官方真相文件");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const reject = async (id: string) => {
    try {
      await api.l2Reject(id);
      flash("已驳回草案");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const redraft = async () => {
    if (!redraftNid) return;
    setBusy("机器起草中(读定稿正文提取事实)…");
    setError("");
    try {
      const l4 = await fetch(`/api/workbench/${redraftNid}/preview?project_id=${pid}`).then((r) => r.json());
      const text = l4.current_text || "";
      if (!text) {
        setError("该章没有定稿正文");
        return;
      }
      const r = await api.l2Redraft(pid, redraftNid, text);
      flash(`起草完成:${(r as { count?: number }).count ?? "?"} 类变更草案待批`);
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <h3>回写草案审核(F9 · 写入协议:机器起草,人批准才入账)</h3>
      <p className="muted small">
        草案是全书真相文件的下一版(每次起草覆盖上一版,不按章分存);定稿任一章自动以该章正文起草,或选章手动触发。
      </p>
      <div className="row">
        <select value={redraftNid} onChange={(e) => setRedraftNid(e.target.value)}>
          <option value="">(选章:手动重新起草的参考章)</option>
          {finalChapters.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
        <button onClick={redraft} disabled={!!busy || !redraftNid}>重新起草 L2 diff</button>
      </div>
      {drafts.length === 0 && <p className="muted small">没有待审草案。定稿一章后自动起草,或上方手动触发。</p>}
      <ul className="entry-list">
        {drafts.map((d) => (
          <li key={d.id} className="entry">
            <div className="entry-head">
              <b>{d.file_type}</b>
              <span className="badge warn">待批准</span>
              <span className="muted small">{d.content.length} 字符</span>
              <button className="link" onClick={() => setExpanded(expanded === d.id ? null : d.id)}>
                {expanded === d.id ? "收起" : "对比"}
              </button>
              <button onClick={() => approve(d.id)}>批准入账</button>
              <button onClick={() => reject(d.id)}>驳回</button>
            </div>
            {expanded === d.id && (
              <div className="diff-grid">
                <div>
                  <p className="muted small">当前官方区</p>
                  <pre className="asm-content">{d.before || "(空)"}</pre>
                </div>
                <div>
                  <p className="muted small">草案(批准后替换)</p>
                  <pre className="asm-content">{d.content}</pre>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      <h3>伏笔池看板(F10 · 当前第 {curChapter} 章,超 {staleThreshold} 章未回收标红)</h3>
      {hooks.length === 0 && <p className="muted small">伏笔池为空。</p>}
      {hooks.length > 0 && (
        <table>
          <thead><tr><th>伏笔</th><th>埋于</th><th>龄期</th><th>状态</th></tr></thead>
          <tbody>
            {hooks.map((h, i) => (
              <tr key={i}>
                <td style={h.stale ? { color: "var(--err)" } : undefined}>{h.detail}</td>
                <td>第 {h.planted_chapter} 章</td>
                <td>{h.age} 章</td>
                <td>{h.status}{h.stale ? " ⚠ 烂尾预警" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
