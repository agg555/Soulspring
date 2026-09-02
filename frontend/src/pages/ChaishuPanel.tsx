import { useEffect, useState } from "react";

/**
 * 拆书官(F11)+ 素材库挂载 + MCP 查证(F12):
 * 只读浏览素材库 → 收尾校验 → 批量导入 L1 提案区 → 人批准;
 * 查证 = wiki 优先 → tavily 降级,取证落素材库(来源/时间/置信度)。
 */
export default function ChaishuPanel({ pid }: { pid: string }) {
  const [path, setPath] = useState("");
  const [items, setItems] = useState<{ name: string; dir: boolean; size: number | null }[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [imported, setImported] = useState<string>("");
  const [verifyQuery, setVerifyQuery] = useState("");
  const [evidence, setEvidence] = useState<{ source: string; url: string; content: string; confidence: number; created_at: string }[]>([]);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<{ name: string; content: string } | null>(null);

  // ── 拆书任务(整本 txt → 50章/批断点续跑)──
  const [bookTitle, setBookTitle] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [job, setJob] = useState<{ id: string; book_title: string; total_chapters: number; done_chapters: number; batch_size: number; status: string; output_dir: string } | null>(null);
  const [jobBusy, setJobBusy] = useState(false);

  const createJob = () => {
    if (!bookTitle.trim() || !sourcePath.trim()) {
      setError("书名与源 txt 路径必填");
      return;
    }
    setJobBusy(true);
    setError("");
    fetch(`/api/chaishu/job?project_id=${pid}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, book_title: bookTitle.trim(), source_path: sourcePath.trim(), batch_size: 50 }),
    })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(JSON.stringify(d.detail ?? d).slice(0, 200));
        setJob(d.job);
        flash(`任务已建:${d.job.total_chapters} 章,${Math.ceil(d.job.total_chapters / d.job.batch_size)} 批`);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setJobBusy(false));
  };

  const runJob = () => {
    if (!job) return;
    setJobBusy(true);
    setError("");
    fetch(`/api/chaishu/job/${job.id}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 5 }),
    })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(JSON.stringify(d.detail ?? d).slice(0, 200));
        setJob({ ...job, done_chapters: d.done, status: d.finished ? "done" : "paused" });
        flash(`已拆 ${d.done}/${d.total} 章${d.finished ? ",任务完成!" : ",可继续点「跑 5 章」"}`);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setJobBusy(false));
  };

  const loadJob = () => {
    fetch(`/api/chaishu/jobs?project_id=${pid}`)
      .then((r) => r.json())
      .then((d) => {
        const j = d.jobs?.[0];
        if (j) setJob(j);
      })
      .catch(() => {});
  };
  useEffect(loadJob, [pid]);


  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 4000);
  };

  const browse = (p: string) => {
    fetch(`/api/chaishu/browse?path=${encodeURIComponent(p)}`)
      .then((r) => r.json())
      .then((d) => {
        setItems(d.items);
        setParent(d.parent);
        setPath(d.path);
      })
      .catch((e) => setError(String(e.message || e)));
  };
  useEffect(() => { browse(""); }, []);

  const openItem = (name: string, dir: boolean) => {
    const child = path ? `${path}\\${name}` : `${path}${name}`;
    if (dir) browse(child);
    else
      fetch(`/api/chaishu/file?path=${encodeURIComponent(child)}`)
        .then((r) => r.json())
        .then((d) => setPreview({ name, content: d.content ?? String(d.detail ?? d) }))
        .catch((e) => setError(String(e.message || e)));
  };

  const validate = () => {
    setBusy("校验中…");
    fetch(`/api/chaishu/validate?path=${encodeURIComponent(path)}`)
      .then((r) => r.json())
      .then((d) => {
        setReport(d);
        flash(d.pass ? "收尾校验通过" : "校验未通过,详见报告");
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setBusy(""));
  };

  const runImport = () => {
    setBusy("导入中(批量写入提案区)…");
    setError("");
    fetch(`/api/chaishu/import?project_id=${pid}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, source_path: path }),
    })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(JSON.stringify(d.detail ?? d).slice(0, 200));
        setImported(`导入 ${d.imported} 条提案:${Object.entries(d.per_category).map(([k, v]) => `${k}×${v}`).join(",")}(去 L1 档案库批准)`);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setBusy(""));
  };

  const verify = () => {
    if (!verifyQuery.trim()) return;
    setBusy("查证中(wiki 优先→tavily 降级)…");
    setError("");
    fetch(`/api/chaishu/verify?project_id=${pid}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: pid, query: verifyQuery.trim(), lang: "zh" }),
    })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(JSON.stringify(d.detail ?? d).slice(0, 200));
        flash(`查证完成(via ${d.via}),${d.count} 条素材入库,耗时 ${d.duration_ms}ms`);
        loadEvidence();
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setBusy(""));
  };
  const loadEvidence = () => {
    fetch(`/api/chaishu/evidence?project_id=${pid}`)
      .then((r) => r.json())
      .then((d) => setEvidence(d.evidence))
      .catch(() => {});
  };
  useEffect(loadEvidence, [pid]);

  return (
    <div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}
      {busy && <p className="muted">{busy}</p>}

      <h3>素材库浏览(只读)</h3>
      <p className="muted small">{path || "(素材库根目录)"}</p>
      <ul className="entry-list">
        {parent && <li className="entry"><button className="link" onClick={() => browse(parent)}>↩ 上一级</button></li>}
        {items.map((it) => (
          <li key={it.name} className="entry">
            <button className="link" onClick={() => openItem(it.name, it.dir)}>
              {it.dir ? "📁" : "📄"} {it.name}
            </button>
            {!it.dir && it.size != null && <span className="muted small">{(it.size / 1024).toFixed(1)}K</span>}
          </li>
        ))}
      </ul>
      {preview && (
        <div className="dialog">
          <div className="row spread">
            <b>{preview.name}</b>
            <button className="link" onClick={() => setPreview(null)}>关闭</button>
          </div>
          <pre className="asm-content">{preview.content.slice(0, 3000)}</pre>
        </div>
      )}

      <h3>拆书导入(F11 · 收尾校验 + 批量入提案区)</h3>
      <p className="muted small">定位到拆书成果根目录(含 概要/拆文报告/文风/章节/角色/设定),先校验后导入;导入全部为提案,去 L1 档案库批准。</p>
      <div className="row">
        <button onClick={validate} disabled={!!busy}>① 收尾校验</button>
        <button className="primary" onClick={runImport} disabled={!!busy}>② 批量导入提案区</button>
      </div>
      {report && (
        <pre className="asm-content">{JSON.stringify(report, null, 1).slice(0, 800)}</pre>
      )}
      {imported && <p className="ok">{imported}</p>}


      <h3>整本拆书任务(F11 · txt → 章节摘要,断点续跑)</h3>
      <p className="muted small">
        适合 600 万字级整本:切分章节边界 → 按 50 章/批逐章拆摘要(免费模型约 1-2 分钟/章,可反复点"跑 5 章"续跑)。
        拆完的摘要可批量进提案区(用"批量导入提案区"指向任务输出目录)。
      </p>
      <div className="form">
        <label>书名<input value={bookTitle} onChange={(e) => setBookTitle(e.target.value)} placeholder="如:神秘复苏" /></label>
        <label>源 txt 路径<input value={sourcePath} onChange={(e) => setSourcePath(e.target.value)} placeholder="E:/.../原文.txt" /></label>
      </div>
      <div className="row">
        <button onClick={createJob} disabled={jobBusy}>① 建任务(切分章节)</button>
        {job && <button className="primary" onClick={runJob} disabled={jobBusy}>② 跑 5 章</button>}
      </div>
      {job && (
        <p className="small">
          任务:{job.book_title} · <b>{job.done_chapters} / {job.total_chapters}</b> 章(每批 {job.batch_size} 章,共 {Math.ceil(job.total_chapters / job.batch_size)} 批) · 状态:{job.status}
        </p>
      )}

      <h3>查证(F12 · wiki 优先 → tavily 降级 → 素材库)</h3>
      <div className="row">
        <input value={verifyQuery} onChange={(e) => setVerifyQuery(e.target.value)}
          placeholder="查证关键词,如:恐怖复苏 设定" />
        <button className="primary" onClick={verify} disabled={!!busy}>查证</button>
      </div>
      {evidence.length > 0 && (
        <table>
          <thead><tr><th>时间(UTC)</th><th>来源</th><th>内容</th><th>置信度</th></tr></thead>
          <tbody>
            {evidence.map((e, i) => (
              <tr key={i}>
                <td>{e.created_at.replace("T", " ").slice(0, 16)}</td>
                <td>{e.source}</td>
                <td style={{ maxWidth: 380 }}>
                  <a href={e.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>{e.url.slice(0, 50)}</a>
                  <div className="muted small">{e.content.slice(0, 80)}…</div>
                </td>
                <td>{e.confidence?.toFixed?.(2) ?? e.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
