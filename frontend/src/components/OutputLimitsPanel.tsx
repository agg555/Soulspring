import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LimitPair, OutputLimits, Settings } from "../types";

/**
 * 输出上下限总览面板(2026-09-09 拍板:全部触点/下限=告警线/三层优先级/选书全览+搜索)。
 * - 全局默认 min/max(未配=按出厂登记);
 * - 选书后:本书默认 + 本书×触点覆盖表(搜索过滤;清空保存=删除该层覆盖);
 * - 生效值列=前端按解析链复算(书×触点>书默认>触点覆盖>全局默认>登记),
 *   与后端 _resolve_* 同链,只作展示,真值以后端解析为准。
 * 触点级上限的"全局覆盖"在设置页「触点覆盖」表(touches)编辑,此处不重复给入口。
 */
const REG_MAX: Record<string, number | null> = {
  review_chat: 8000, chat_test: 8000, outline_chat: 8000, book_chat: 8000, l1_chat: 8000,
  chapter_plan: 8000, chapter_draft: 24000, chapter_normalize: 16000, chapter_review: 8000,
  chapter_repair: 24000, build_proposal: 32000, l1_field_fill: null,
  l2_rewrite_draft: 6000, chaishu_summary: 8000, chaishu_organize: 8000, llm_test: 512,
  outline_subtopic_split: 8000, outline_body_suggest: 4000,
};
const ALL_ACTIONS = Object.keys(REG_MAX);

interface BookRow { id: string; name: string }

export default function OutputLimitsPanel({ s, flash, onChanged }: {
  s: Settings;
  flash: (t: string) => void;
  onChanged: (fresh: Settings) => void;
}) {
  const [books, setBooks] = useState<BookRow[]>([]);
  const [book, setBook] = useState("");            // ""=全局层
  const [q, setQ] = useState("");
  const [gMin, setGMin] = useState("");
  const [gMax, setGMax] = useState("");
  const [bMin, setBMin] = useState("");
  const [bMax, setBMax] = useState("");
  // 本书×触点覆盖的编辑缓冲(action → {min,max} 草稿)
  const [rows, setRows] = useState<Record<string, { min: string; max: string }>>({});
  const [busy, setBusy] = useState(false);
  const limits: OutputLimits = s.output_limits ?? { default: {}, books: {} };

  useEffect(() => {
    api.overview().then((o) => {
      const list: BookRow[] = (o.projects ?? []).map((p) => ({ id: p.id, name: p.name }))
        .filter((b) => !b.name.startsWith("__"));
      setBooks(list);
    }).catch(() => {});
  }, []);

  // 选书切换 → 回填本书编辑缓冲
  useEffect(() => {
    setGMin(String(limits.default?.min_tokens ?? ""));
    setGMax(String(limits.default?.max_tokens ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limits.default?.min_tokens, limits.default?.max_tokens]);
  useEffect(() => {
    const b = book ? (limits.books ?? {})[book] : null;
    setBMin(String(b?.default?.min_tokens ?? ""));
    setBMax(String(b?.default?.max_tokens ?? ""));
    const next: Record<string, { min: string; max: string }> = {};
    for (const a of ALL_ACTIONS) {
      const ov = b?.actions?.[a] ?? {};
      next[a] = { min: String(ov.min_tokens ?? ""), max: String(ov.max_tokens ?? "") };
    }
    setRows(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book, limits]);

  const saveGlobal = async () => {
    setBusy(true);
    try {
      const r = await api.putOutputLimits({
        default: {
          min_tokens: gMin.trim() ? Number(gMin) : null,
          max_tokens: gMax.trim() ? Number(gMax) : null,
        },
      });
      flash("全局默认上下限已保存");
      return r.output_limits;
    } finally { setBusy(false); }
  };
  const saveBookDefault = async () => {
    if (!book) return;
    setBusy(true);
    try {
      const cur = (limits.books ?? {})[book] ?? {};
      const r = await api.putOutputLimits({ books: { [book]: {
        default: {
          min_tokens: bMin.trim() ? Number(bMin) : null,
          max_tokens: bMax.trim() ? Number(bMax) : null,
        },
        actions: cur.actions ?? {},
      } } });
      flash("本书默认上下限已保存");
      return r.output_limits;
    } finally { setBusy(false); }
  };
  const saveRow = async (action: string) => {
    if (!book) return;
    setBusy(true);
    try {
      const r0 = rows[action] ?? { min: "", max: "" };
      const cur = (limits.books ?? {})[book] ?? {};
      const actions = { ...(cur.actions ?? {}) };
      const pair: LimitPair = {
        min_tokens: r0.min.trim() ? Number(r0.min) : null,
        max_tokens: r0.max.trim() ? Number(r0.max) : null,
      };
      if (pair.min_tokens == null && pair.max_tokens == null) delete actions[action];
      else actions[action] = pair;
      const r = await api.putOutputLimits({ books: { [book]: {
        default: cur.default ?? {}, actions } } });
      flash(`「${action}」本书覆盖已保存`);
      return r.output_limits;
    } finally { setBusy(false); }
  };
  // 保存后用返回的新 limits 刷新宿主 Settings(避免整页重拉)
  const applyLimits = (next?: OutputLimits) => {
    if (next) onChanged({ ...s, output_limits: next });
  };

  // 生效值(展示口径,与后端解析链一致)
  const effective = (action: string): { min: string; max: string } => {
    const b = book ? (limits.books ?? {})[book] : null;
    const ba = b?.actions?.[action] ?? {};
    const reg = REG_MAX[action];
    const max = ba.max_tokens ?? b?.default?.max_tokens
      ?? (s.touches?.[action]?.max_tokens ?? null) ?? limits.default?.max_tokens ?? reg;
    const min = ba.min_tokens ?? b?.default?.min_tokens ?? limits.default?.min_tokens;
    return { min: min ? String(min) : "—", max: max ? String(max) : "—" };
  };

  const actions = useMemo(() => ALL_ACTIONS.filter((a) => {
    if (!q.trim()) return true;
    const label = s.touches_registry?.[a]?.label ?? "";
    return a.includes(q.trim()) || label.includes(q.trim());
  }), [q, s.touches_registry]);
  const touchMax = (a: string) => s.touches?.[a]?.max_tokens ?? null;

  return (
    <div>
      <p className="muted small">
        生效链:本书×触点 &gt; 本书默认 &gt; 触点覆盖 &gt; 全局默认 &gt; 出厂登记。
        下限=告警线(回包低于下限会黄条提示,不硬拦——模型 API 无硬下限)。
      </p>
      <div className="row">
        <b>全局默认</b>
        <label>下限(告警)<input className="w-temp" type="number" value={gMin}
          onChange={(e) => setGMin(e.target.value)} placeholder="—" /></label>
        <label>上限<input className="w-temp" type="number" value={gMax}
          onChange={(e) => setGMax(e.target.value)} placeholder="—" /></label>
        <button disabled={busy} onClick={() => saveGlobal().then(applyLimits)}>保存全局</button>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <b>按书查看/覆盖:</b>
        <select value={book} onChange={(e) => setBook(e.target.value)}>
          <option value="">(不选书——只看全局)</option>
          {books.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <input placeholder="🔍 搜索触点(名称/宿主)…" value={q}
          onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
      </div>
      {book && (
        <div className="row" style={{ marginTop: 6 }}>
          <b>本书默认</b>
          <label>下限<input className="w-temp" type="number" value={bMin}
            onChange={(e) => setBMin(e.target.value)} placeholder="—" /></label>
          <label>上限<input className="w-temp" type="number" value={bMax}
            onChange={(e) => setBMax(e.target.value)} placeholder="—" /></label>
          <button disabled={busy} onClick={() => saveBookDefault().then(applyLimits)}>保存本书默认</button>
        </div>
      )}
      <table style={{ width: "100%", marginTop: 8, fontSize: 12 }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>触点</th>
            <th>登记上限</th>
            <th>触点覆盖上限</th>
            {book && <th style={{ textAlign: "left" }}>本书覆盖(下限/上限)</th>}
            <th>当前生效(下限~上限)</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((a) => {
            const eff = effective(a);
            const r = rows[a] ?? { min: "", max: "" };
            return (
              <tr key={a}>
                <td><b>{s.touches_registry?.[a]?.label ?? a}</b>
                  <span className="muted small">({a})</span></td>
                <td style={{ textAlign: "center" }}>{REG_MAX[a] ?? "—"}</td>
                <td style={{ textAlign: "center" }}>{touchMax(a) ?? "—"}</td>
                {book && (
                  <td>
                    <span className="row" style={{ gap: 4, margin: 0 }}>
                      <input className="w-temp" type="number" title="本书下限(告警线)"
                        value={r.min} placeholder="—"
                        onChange={(e) => setRows({ ...rows, [a]: { ...r, min: e.target.value } })} />
                      <input className="w-temp" type="number" title="本书上限"
                        value={r.max} placeholder="—"
                        onChange={(e) => setRows({ ...rows, [a]: { ...r, max: e.target.value } })} />
                      <button className="link" disabled={busy}
                        onClick={() => saveRow(a).then(applyLimits)}>存</button>
                    </span>
                  </td>
                )}
                <td style={{ textAlign: "center" }}>{eff.min} ~ {eff.max}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!book && (
        <p className="muted small">提示:触点级上限的全局覆盖(不分公司)在下方「触点覆盖」表编辑;选择某本书后,此处可直编本书覆盖。</p>
      )}
    </div>
  );
}
