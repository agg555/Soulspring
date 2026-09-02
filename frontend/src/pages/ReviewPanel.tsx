import { useEffect, useState } from "react";
import { api } from "../api";
import ChatPanel from "../components/ChatPanel";
import type { OutlineNode } from "../types";

/**
 * 终审对话台(F8,7 页之一):
 * 对话区 = 统一 ChatPanel(A3:多线会话 + 发送任务化 + 建议块两档采纳 + @引用);
 * 本页保留:章节选择 / 通过→定稿 / 打回 / 朱雀登记。
 * 通过 = 定稿:自动合入正文(l4+.md)并触发 L2 回写起草。
 */
export default function ReviewPanel({ pid }: { pid: string }) {
  const [chapters, setChapters] = useState<OutlineNode[]>([]);
  const [nid, setNid] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [rejectNote, setRejectNote] = useState("");
  const [zqRows, setZqRows] = useState<Record<string, unknown>[]>([]);
  const [zqRemind, setZqRemind] = useState(false);
  const [zqVerdict, setZqVerdict] = useState("人工");
  const [zqHuman, setZqHuman] = useState("");
  const [zqSuspect, setZqSuspect] = useState("");
  const [zqRed, setZqRed] = useState("0");
  const [zqRedSeg, setZqRedSeg] = useState("");
  const [zqYellowSeg, setZqYellowSeg] = useState("");
  const [zqGreenSeg, setZqGreenSeg] = useState("");

  const loadChapters = () => {
    api.outline(pid).then((r) => {
      const chs = r.nodes.filter((n) => n.kind === "chapter");
      setChapters(chs);
      setNid((cur) => (cur && chs.some((c) => c.id === cur) ? cur : chs[0]?.id ?? null));
    }).catch((e) => setError(String(e.message || e)));
  };
  const loadZhuque = () => {
    api.zhuqueRows(pid).then((r) => {
      setZqRows(r.rows);
      setZqRemind(r.weekly_reminder);
    }).catch(() => {});
  };
  useEffect(() => {
    loadChapters();
    loadZhuque();
  }, [pid]);

  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 5000);
  };

  const approve = async () => {
    if (!nid) return;
    setBusy("定稿中(合入正文 + 触发 L2 回写起草)…");
    setError("");
    try {
      const r = await api.approveFinal(nid, pid);
      flash(`已定稿(revision ${r.applied.revision}),L2 回写草案 ${r.l2_rewrite?.count ?? "?"} 条待批准`);
      loadChapters();
      loadZhuque();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy("");
    }
  };

  const reject = async () => {
    if (!nid) return;
    try {
      await api.rejectFinal(nid, pid, rejectNote);
      flash("已打回人改中");
      setRejectNote("");
      loadChapters();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const logZhuque = async () => {
    try {
      await api.zhuqueLog({
        project_id: pid, node_id: nid, verdict: zqVerdict,
        human_ratio: zqHuman ? Number(zqHuman) : null,
        suspect_ratio: zqSuspect ? Number(zqSuspect) : null,
        red_count: zqRed ? Number(zqRed) : null,
        note: "",
        red_segments: zqRedSeg.split(String.fromCharCode(10)).filter((x) => x.trim()),
        yellow_segments: zqYellowSeg.split(String.fromCharCode(10)).filter((x) => x.trim()),
        green_segments: zqGreenSeg.split(String.fromCharCode(10)).filter((x) => x.trim()),
      });
      flash("朱雀判定已登记(日志五件套之五)");
      loadZhuque();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const chapter = chapters.find((c) => c.id === nid);

  return (
    <div>
      {zqRemind && <p className="error">⏰ 周一提醒:本周还没有朱雀复测登记,请补登记行。</p>}
      <div className="row">
        <select value={nid ?? ""} onChange={(e) => setNid(e.target.value)}>
          {chapters.map((c) => <option key={c.id} value={c.id}>{c.title}({c.status_label})</option>)}
        </select>
        {chapter && <span className={`badge ${chapter.status === "finalized" ? "ok" : ""}`}>{chapter.status_label}</span>}
      </div>
      {chapter?.status === "final_review" && (
        <div className="dialog">
          <p><b>本章待终审。</b>在下方对话台载入违禁检查等技能跑一轮真实审稿,朱雀+本人判定后:通过即定稿,或打回人改。</p>
          <div className="row">
            <input placeholder="打回备注(可选)" value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} />
            <button className="primary" onClick={approve} disabled={!!busy}>通过 → 定稿</button>
            <button onClick={reject} disabled={!!busy}>打回</button>
          </div>
        </div>
      )}
      {busy && <p className="muted">{busy}</p>}
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <ChatPanel
        projectId={pid}
        ownerType="review"
        ownerId={nid}
        defaultSessionName={chapter ? `主讨论·${chapter.title}` : "主讨论"}
        allowSkill
        allowTemp
        allowRefs
        emptyHint="还没有对话。选技能(如「违禁检查」),输入审稿要求发送;本章正文会自动作为附件,@引用 可附加其他章/角色/条目/伏笔。"
        onAdopted={(t) => { if (t === "outline_field") loadChapters(); }}
      />

      <h3>朱雀判定登记(每周复测)</h3>
      <div className="row">
        <select value={zqVerdict} onChange={(e) => setZqVerdict(e.target.value)}>
          <option>人工</option><option>疑似</option><option>红段</option>
        </select>
        <input className="w-narrow" type="number" step="0.1" placeholder="人工%" value={zqHuman} onChange={(e) => setZqHuman(e.target.value)} />
        <input className="w-narrow" type="number" step="0.1" placeholder="疑似%" value={zqSuspect} onChange={(e) => setZqSuspect(e.target.value)} />
        <input className="w-narrow" type="number" placeholder="红段数" value={zqRed} onChange={(e) => setZqRed(e.target.value)} />
        <button onClick={logZhuque} disabled={!!busy}>登记</button>
      </div>
      <div className="form">
        <label>红段位置(每行一条:段落号/摘录)<textarea rows={2} value={zqRedSeg} onChange={(e) => setZqRedSeg(e.target.value)} /></label>
        <label>黄段(疑似)位置<textarea rows={2} value={zqYellowSeg} onChange={(e) => setZqYellowSeg(e.target.value)} /></label>
        <label>绿段(人工)位置<textarea rows={2} value={zqGreenSeg} onChange={(e) => setZqGreenSeg(e.target.value)} /></label>
      </div>
      {zqRows.length > 0 && (
        <table>
          <thead><tr><th>时间(UTC)</th><th>判定</th><th>人工%</th><th>疑似%</th><th>红段</th></tr></thead>
          <tbody>
            {zqRows.map((r, i) => (
              <tr key={i}>
                <td>{String(r.created_at).replace("T", " ").slice(0, 16)}</td>
                <td>{String(r.verdict)}</td>
                <td>{r.human_ratio == null ? "—" : String(r.human_ratio)}</td>
                <td>{r.suspect_ratio == null ? "—" : String(r.suspect_ratio)}</td>
                <td>{r.red_count == null ? "—" : String(r.red_count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
