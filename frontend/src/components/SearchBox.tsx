import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SearchGroup, SearchResponse } from "../types";

/**
 * 全局搜索框(批次七②):FTS5 trigram 分层搜索,浮层按版块分组。
 * 点击跳转走面板宿主既有枢纽:章节→写章工作台,大纲/条目/时间线→互链抽屉路由,
 * 零新壳。250ms 防抖;1-2 字短查由后端 LIKE 兜底,前端不设长度门槛。
 */
const GROUP_ETYPE: Record<SearchGroup["group"], string | null> = {
  chapter: null,             // 章节→工作台直达
  outline: "outline_node",
  entry: "l1_entry",
  timeline: "timeline_event",
};

export default function SearchBox({ pid, onGoChapter, onJumpEntity }: {
  pid: string;
  onGoChapter: (nid: string, title: string) => void;
  onJumpEntity: (etype: string, id: string, title: string) => void;
}) {
  const [q, setQ] = useState("");
  const [resp, setResp] = useState<SearchResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (!query) { setResp(null); setOpen(false); return; }
    const timer = setTimeout(() => {
      setBusy(true);
      api.search(query, pid)
        .then((r) => { setResp(r); setOpen(true); })
        .catch(() => setResp(null))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [q, pid]);

  // 点框外收起(与抽屉点外关闭同纪律)
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const pick = (g: SearchGroup["group"], refId: string, title: string) => {
    setOpen(false);
    const etype = GROUP_ETYPE[g];
    if (etype) onJumpEntity(etype, refId, title);
    else onGoChapter(refId, title);
  };

  const hit = (g: SearchGroup[]) => g.some((x) => x.items.length > 0);

  return (
    <div className="gsearch" ref={boxRef}>
      <input
        value={q}
        placeholder="🔍 搜本书:人名/子串…"
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => { if (resp) setOpen(true); }}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
      />
      {busy && <span className="gsearch-busy">…</span>}
      {open && resp && (
        <div className="gsearch-pop">
          {!hit(resp.groups) && <p className="muted small gsearch-empty">没有「{resp.q}」的结果</p>}
          {hit(resp.groups) && resp.groups.map((g) => (
            g.items.length > 0 && (
              <div key={g.group} className="gsearch-group">
                <p className="gsearch-group-label">{g.label}({g.items.length})</p>
                {g.items.map((it) => (
                  <button key={it.ref_id} className="gsearch-item"
                    onMouseDown={(e) => { e.preventDefault(); pick(g.group, it.ref_id, it.title); }}>
                    <b>{it.title}</b>
                    {it.snippet && <span className="muted small">{it.snippet}</span>}
                  </button>
                ))}
              </div>
            )
          ))}
          {hit(resp.groups) && (
            <p className="muted small gsearch-foot">{resp.total} 条 · {resp.elapsed_ms}ms</p>
          )}
        </div>
      )}
    </div>
  );
}
