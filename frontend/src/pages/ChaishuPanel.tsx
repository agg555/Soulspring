import { useEffect, useState } from "react";
import { api } from "../api";

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
  const [pendingImport, setPendingImport] = useState<{ count: number; head: string } | null>(null);
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

  // 批次二 AI 流升级:导入前逐条预览(不写库),内联确认后才是 doImport
  const runImport = async () => {
    setError("");
    try {
      const pv = await api.chaishuImportPreview(path);
      const head = pv.names.slice(0, 12).map((n: { category: string; name: string }) => `${n.category}/${n.name}`).join("、");
      setPendingImport({ count: pv.count, head: head + (pv.count > 12 ? " 等" : "") });
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const doImport = () => {
    setPendingImport(null);
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

      <h3>拆书导入(收尾校验 + 批量入提案区)</h3>
      <p className="muted small">定位到拆书成果根目录(含 概要/拆文报告/文风/章节/角色/设定),先校验后导入;导入全部为提案,去 L1 档案库批准。</p>
      <div className="row">
        <button onClick={validate} disabled={!!busy}>① 收尾校验</button>
        <button className="primary" onClick={runImport} disabled={!!busy}>② 预览并导入提案区</button>
        {pendingImport && (
          <div className="log-box">
            <p><b>将导入 {pendingImport.count} 条提案</b>(不直接入正式档案,导入后去 L1 档案库逐条批准):</p>
            <p className="muted small">{pendingImport.head}</p>
            <div className="row">
              <button onClick={() => setPendingImport(null)}>取消</button>
              <button className="primary" onClick={doImport} disabled={!!busy}>确认导入</button>
            </div>
          </div>
        )}
      </div>
      {report && (
        <pre className="asm-content">{JSON.stringify(report, null, 1).slice(0, 800)}</pre>
      )}
      {imported && <p className="ok">{imported}</p>}


      <TextImportSection pid={pid} flash={flash} />

      <h3>整本拆书任务（整本 txt → 章节摘要，断点续跑）</h3>
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

      <h3>查证（维基优先 → 联网搜索降级 → 素材库）</h3>
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

// ── 批次三①:文本导入(拆书官第二模式;纯算法切分,整批提案闸门,执行书 §2①)──
function TextImportSection({ pid, flash }: { pid: string; flash: (m: string) => void }) {
  const [text, setText] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [target, setTarget] = useState<"outline" | "manuscript" | "l1">("outline");
  const [volumeId, setVolumeId] = useState("");
  const [volumes, setVolumes] = useState<{ id: string; title: string }[]>([]);
  const [preview, setPreview] = useState<null | {
    chapters: { index: number; title: string; chars: number; content: string }[];
    warnings: string[];
    total_chars: number;
  }>(null);
  const [jobs, setJobs] = useState<null | {
    id: string; source_name: string; target: string; volume_id: string | null;
    status: string; count: number; titles: string[]; warnings: string[];
  }[]>(null);
  const [busy, setBusy] = useState(false);
  const [orgOn, setOrgOn] = useState(false);   // 整理官本次会话内启用(总闸在设置页,默认关)
  const [orgText, setOrgText] = useState<{ source: string; suggestion: string; cost: number } | null>(null);

  const loadJobs = () => {
    api.textImports(pid).then((d) => setJobs(d.jobs)).catch(() => {});
  };
  useEffect(() => {
    api.outline(pid)
      .then((r) => setVolumes(r.nodes
        .filter((n) => n.kind === "volume" || n.kind === "arc")
        .map((n) => ({ id: n.id, title: n.title }))))
      .catch(() => {});
    loadJobs();
  }, [pid]);

  const doPreview = () => {
    setBusy(true);
    api.textSplit(text)
      .then(setPreview)
      .catch((e) => flash(`切分失败:${String((e as Error).message || e)}`))
      .finally(() => setBusy(false));
  };

  // ①AI 整理官(默认关;总闸在设置页,这里再显式勾选才调用;第三方拆书内容场景)
  const organizeFirst = () => {
    const first = preview?.chapters?.[0];
    if (!first) { flash("请先预览切分"); return; }
    setBusy(true);
    api.textOrganize(first.content)
      .then((r) => setOrgText({ source: first.title, suggestion: r.suggestion, cost: r.cost }))
      .catch((e) => flash(`整理失败:${String((e as Error).message || e)}`))
      .finally(() => setBusy(false));
  };

  const submit = () => {
    if (target !== "l1" && !volumeId) { flash("该去向需先选目标卷/近纲"); return; }
    setBusy(true);
    api.textImportCreate({
      project_id: pid, text, source_name: sourceName, target,
      volume_id: target === "l1" ? null : volumeId,
    })
      .then((r) => {
        flash(r.message);
        setPreview(null);
        loadJobs();
      })
      .catch((e) => flash(`提交失败:${String((e as Error).message || e)}`))
      .finally(() => setBusy(false));
  };

  const decide = (jid: string, approve: boolean) => {
    setBusy(true);
    const fail = (e: unknown) => flash(`操作失败:${String((e as Error).message || e)}`);
    if (approve) {
      api.textImportApprove(jid, {})
        .then((r) => { flash(`已批准,落库 ${r.created} 章`); loadJobs(); })
        .catch(fail)
        .finally(() => setBusy(false));
    } else {
      api.textImportReject(jid)
        .then(() => { flash("已驳回"); loadJobs(); })
        .catch(fail)
        .finally(() => setBusy(false));
    }
  };

  return (
    <>
      <h3>文本导入(第二模式 · 纯算法切分,不重排)</h3>
      <p className="muted small">
        自有大纲/小说:粘贴或选 .txt/.md,识别「第X章」标记(无标记按 Markdown 一级标题兜底)。
        大纲/正文去向=整批一条提案,看过逐章明细批准后才落库;L1 去向直接进提案区逐条批准。
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder="粘贴全文,或下方选文件…"
        style={{ width: "100%" }}
      />
      <div className="row">
        <input type="file" accept=".txt,.md,text/plain"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setSourceName(f.name);
            f.text().then(setText).catch(() => flash("文件读取失败"));
          }} />
        <input value={sourceName} onChange={(e) => setSourceName(e.target.value)}
          placeholder="来源名(可选)" style={{ width: 140 }} />
        <select value={target} onChange={(e) => setTarget(e.target.value as typeof target)}>
          <option value="outline">去向:大纲建章(结构导入)</option>
          <option value="manuscript">去向:正文(建章+每章正文)</option>
          <option value="l1">去向:L1 设定条目(进提案区)</option>
        </select>
        {target !== "l1" && (
          <select value={volumeId} onChange={(e) => setVolumeId(e.target.value)}>
            <option value="">选目标卷/近纲…</option>
            {volumes.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
          </select>
        )}
        <button onClick={doPreview} disabled={busy || !text.trim()}>① 预览切分</button>
        <label className="row small" title="默认关;总闸在设置页「界面」组。只建议用于第三方拆书内容">
          <input type="checkbox" checked={orgOn}
            onChange={(e) => setOrgOn(e.target.checked)} /> AI 整理官
        </label>
        {orgOn && preview && (
          <button className="link" onClick={organizeFirst} disabled={busy}>
            🪄 整理第一节(出建议,人工对比采用)
          </button>
        )}
      </div>
      {orgText && (
        <div className="card">
          <b>整理建议:{orgText.source}</b>
          <span className="muted small">(成本 ¥{orgText.cost.toFixed(4)};仅建议,不直接改原文)</span>
          <pre style={{ maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap" }}>{orgText.suggestion}</pre>
          <button className="link" onClick={() => setOrgText(null)}>关闭</button>
        </div>
      )}
      {preview && (
        <div className="card">
          <b>切分预览:{preview.chapters.length} 节 / {preview.total_chars} 字</b>
          {preview.warnings.map((w, i) => (
            <div key={i}><span className="badge warn">{w}</span></div>
          ))}
          <div style={{ maxHeight: 180, overflow: "auto", marginTop: 6 }}>
            {preview.chapters.map((c) => (
              <div key={c.index} className="muted small">
                {c.index + 1}. {c.title}({c.chars} 字)
              </div>
            ))}
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="primary" onClick={submit} disabled={busy}>② 提交导入提案</button>
            <button onClick={() => setPreview(null)}>取消</button>
          </div>
        </div>
      )}
      {jobs && jobs.length > 0 && (
        <>
          <b className="small">导入提案(整批一条,批准才落库):</b>
          {jobs.map((j) => (
            <div key={j.id} className="card">
              <b>{j.source_name || "(未命名)"}</b> · {j.target === "manuscript" ? "正文" : "大纲"}
              · {j.count} 章 ·{" "}
              <span className={j.status === "awaiting_approval" ? "badge warn" : "badge"}>
                {j.status === "awaiting_approval" ? "待批准"
                  : j.status === "approved" ? "已批准" : "已驳回"}
              </span>
              <div className="muted small">{j.titles.join("、")}{j.count > 8 ? "…" : ""}</div>
              {j.warnings.map((w, i) => <div key={i}><span className="badge warn">{w}</span></div>)}
              {j.status === "awaiting_approval" && (
                <div className="row">
                  <button className="primary" disabled={busy}
                    onClick={() => decide(j.id, true)}>✓ 批准落库</button>
                  <button disabled={busy} onClick={() => decide(j.id, false)}>驳回</button>
                </div>
              )}
            </div>
          ))}
        </>
      )}
    </>
  );
}
