import { useEffect, useState } from "react";
import { api } from "../api";
import type { TimelineEvent } from "../types";

/**
 * 📌 本章卡(二期③,分支打磨 §三;消费者 a=装配注入 b=体检新规 已拍板):
 * 默认收起一行速填条(防触点过载);四行直写既有表——一句话大纲(summary)/
 * 时间关联(event_chapters)/本章人物(人物板同框边,只引用已有人物,≥2 人)/
 * 备注(note)。零 L1/L2 写入,AI 预填走建议闸门另案。
 */
interface CardData {
  node_id: string;
  title: string;
  chapter_no: number | null;
  summary: string;
  note: string;
  events: (TimelineEvent | { id: string; title: string; time_label: string })[];
  linked_event_ids: string[];
  characters: { id: string; label: string; ref_id: string | null }[];
  cast_node_ids: string[];
  has_scenes: boolean;
  scene_cast: string[];
}

export default function ChapterCard({ pid, nid, onChanged }: {
  pid: string;
  nid: string | null;
  onChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [card, setCard] = useState<CardData | null>(null);
  const [summary, setSummary] = useState("");
  const [note, setNote] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [cast, setCast] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  // AI 预填(候选清单落地批 A):建议对象+确认弹窗;人勾选字段后才经 cardSave 落库
  const [aiSug, setAiSug] = useState<{ summary: string; note: string;
    event_titles: string[]; character_labels: string[] } | null>(null);
  const [aiPick, setAiPick] = useState<{ summary: boolean; note: boolean;
    events: boolean; cast: boolean }>({ summary: true, note: true, events: true, cast: true });
  const [aiBusy, setAiBusy] = useState(false);

  useEffect(() => {
    if (!nid) { setCard(null); return; }
    setMsg(""); setError("");
    api.cardGet(nid, pid).then((c) => {
      setCard(c);
      setSummary(c.summary);
      setNote(c.note);
      setEvents(c.linked_event_ids);
      setCast(c.cast_node_ids);
    }).catch((e) => setError(String((e as Error).message || e)));
  }, [nid, pid]);

  const save = async () => {
    setError("");
    try {
      await api.cardSave(nid!, pid, {
        summary, note, event_ids: events, cast_node_ids: cast,
      });
      setMsg("本章卡已保存(直写大纲/时间线/同框边)");
      setTimeout(() => setMsg(""), 3500);
      onChanged?.();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  // AI 预填:只出建议(diff 弹窗勾选);应用=把勾选字段的 AI 值写进表单,再由人点保存
  const runAiFill = async () => {
    setAiBusy(true);
    setError("");
    try {
      const r = await api.cardAiFill(nid!, pid);
      setAiSug({
        summary: r.summary, note: r.note,
        event_titles: r.event_titles, character_labels: r.character_labels,
      });
      setAiPick({ summary: true, note: true, events: true, cast: true });
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setAiBusy(false);
    }
  };
  const applyAiSug = () => {
    if (!aiSug || !card) return;
    if (aiPick.summary) setSummary(aiSug.summary);
    if (aiPick.note) setNote(aiSug.note);
    if (aiPick.events) {
      const ids = card.events.filter((e) => aiSug.event_titles.includes(e.title))
        .map((e) => e.id);
      setEvents(ids);
    }
    if (aiPick.cast) {
      if (card.has_scenes) {
        setMsg("本章有场景:人物以场景卡为准,AI 的人物建议未应用");
      } else {
        const ids = card.characters.filter((c) => aiSug.character_labels.includes(c.label))
          .map((c) => c.id);
        setCast(ids);
      }
    }
    setAiSug(null);
    setMsg("AI 建议已填入表单——核对后点「保存本章卡」才落库");
    setTimeout(() => setMsg(""), 6000);
  };

  if (!nid) return null;
  const filled = [card?.summary, card?.note].some((s) => (s ?? "").trim())
    || (card?.linked_event_ids.length ?? 0) > 0 || (card?.cast_node_ids.length ?? 0) > 0;

  return (
    <div className="chapter-card">
      {/* AI 预填建议确认(候选清单落地批 A):勾选字段→填入表单;保存才落库 */}
      {aiSug && (
        <div className="dialog">
          <p><b>AI 预填建议(批准闸门)</b>:勾选要采用的字段,填入表单后仍需点
            「保存本章卡」才落库。</p>
          <label className="card-check"><input type="checkbox"
            checked={aiPick.summary}
            onChange={(e) => setAiPick({ ...aiPick, summary: e.target.checked })} />
            一句话大纲:{aiSug.summary || "(空)"}</label>
          <label className="card-check"><input type="checkbox"
            checked={aiPick.note}
            onChange={(e) => setAiPick({ ...aiPick, note: e.target.checked })} />
            备注:{aiSug.note || "(空)"}</label>
          <label className="card-check"><input type="checkbox"
            checked={aiPick.events}
            onChange={(e) => setAiPick({ ...aiPick, events: e.target.checked })} />
            关联事件:{aiSug.event_titles.join("、") || "(无命中)"}</label>
          <label className="card-check"><input type="checkbox"
            checked={aiPick.cast}
            onChange={(e) => setAiPick({ ...aiPick, cast: e.target.checked })} />
            本章人物:{aiSug.character_labels.join("、") || "(无命中)"}</label>
          <div className="row">
            <button className="primary" onClick={applyAiSug}>填入表单</button>
            <button onClick={() => setAiSug(null)}>放弃</button>
          </div>
        </div>
      )}
      <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>📌 本章卡{card?.chapter_no != null ? `(第${card.chapter_no}章)` : ""}
          <span className="muted small">{filled ? " · 已填" : " · 未填(写前填目标,写后填事实)"}</span>
          <button className="link" style={{ marginLeft: 8 }}
            disabled={aiBusy || !open}
            title="AI 读本章正文出四行建议;diff 勾选后填入表单,核对保存才落库"
            onClick={(e) => { e.preventDefault(); void runAiFill(); }}>
            {aiBusy ? "⏳ AI 预填中…" : "✨ AI 预填"}
          </button>
        </summary>
        {card && (
          <div className="form card-form">
            <label className="full">一句话大纲(会同步进大纲树与装配上下文)
              <input value={summary} placeholder="本章一句话目标/概要"
                onChange={(e) => setSummary(e.target.value)} />
            </label>
            <label className="full">时间关联(勾选本章触发的剧情事件)
              <span className="card-checks">
                {card.events.length === 0 && <span className="muted small">(本书还没有时间线事件,去「剧情时间线」建)</span>}
                {card.events.map((ev) => (
                  <label key={ev.id} className="card-check">
                    <input type="checkbox" checked={events.includes(ev.id)}
                      onChange={(e) => setEvents((cur) =>
                        e.target.checked ? [...cur, ev.id] : cur.filter((x) => x !== ev.id))} />
                    {ev.title}
                  </label>
                ))}
              </span>
            </label>
            <label className="full">
              {card.has_scenes
                ? <>本章有场景:人物以场景卡为准(聚合:{card.scene_cast.join("、") || "场景未记人物"})——如需调整请去场景卡</>
                : <>本章人物(从人物板里选;至少 2 人才记同框,单人出场请记到场景卡)</>}
              {card.characters.length === 0 && (
                <span className="muted small">(人物板还没有人物节点,去图谱中心人物关系板添加)</span>
              )}
              <span className="card-checks">
                {card.characters.map((c) => (
                  <label key={c.id} className="card-check">
                    <input type="checkbox" disabled={card.has_scenes}
                      checked={cast.includes(c.id)}
                      onChange={(e) => setCast((cur) =>
                        e.target.checked ? [...cur, c.id] : cur.filter((x) => x !== c.id))} />
                    {c.label}
                  </label>
                ))}
              </span>
            </label>
            <label className="full">备注(本章提醒,不进正文)
              <input value={note} placeholder="备注/提醒"
                onChange={(e) => setNote(e.target.value)} />
            </label>
            <div className="row" style={{ margin: 0 }}>
              <button className="primary" onClick={save}>保存本章卡</button>
              {msg && <span className="ok small">{msg}</span>}
            </div>
            {error && <p className="error">{error}</p>}
          </div>
        )}
      </details>
    </div>
  );
}
