import { useEffect, useState } from "react";
import { api } from "../api";
import type { F0Options } from "../types";

interface Draft {
  name: string;
  genre: string;
  protagonist: string;
  tropes: string[];
  audience: string;
  style: string[];
  plot_mode: string;
  power_preset: string;
  cheat_preset: string;
  core_conflict: string;
  chapter_words: string;
  target_words: string;
  description: string;
}

const EMPTY: Draft = {
  name: "", genre: "", protagonist: "", tropes: [], audience: "",
  style: [], plot_mode: "", power_preset: "", cheat_preset: "",
  core_conflict: "", chapter_words: "", target_words: "", description: "",
};

export default function NewBookWizard({
  onDone,
  onCancel,
}: {
  onDone: (pid: string) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(1);
  const [opt, setOpt] = useState<F0Options | null>(null);
  const [d, setD] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.options().then(setOpt).catch((e) => setError(String(e.message || e)));
  }, []);

  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch });
  const toggle = (field: "tropes" | "style", v: string) =>
    set({
      [field]: d[field].includes(v) ? d[field].filter((x) => x !== v) : [...d[field], v],
    } as Partial<Draft>);

  const submit = async () => {
    if (!d.name.trim()) {
      setError("书名必填");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await api.createProject({
        name: d.name,
        genre: d.genre || null,
        protagonist: d.protagonist || null,
        tropes: d.tropes,
        audience: d.audience || null,
        style: d.style,
        plot_mode: d.plot_mode || null,
        power_preset: d.power_preset || null,
        cheat_preset: d.cheat_preset || null,
        core_conflict: d.core_conflict || null,
        chapter_words: d.chapter_words ? Number(d.chapter_words) : null,
        target_words: d.target_words ? Number(d.target_words) : null,
        description: d.description || null,
      });
      onDone(r.id);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
      setBusy(false);
    }
  };

  if (error && !opt) return <p className="error">{error}</p>;
  if (!opt) return <p className="muted">加载字典中…</p>;

  return (
    <div className="wizard">
      <div className="wizard-head">
        <h3>新建书向导</h3>
        <span className="muted">第 {step} / 2 步 · 选项字典来自云笔数据(F0)</span>
      </div>
      {error && <p className="error">{error}</p>}

      {step === 1 && (
        <div className="form">
          <label>
            书名 *
            <input value={d.name} onChange={(e) => set({ name: e.target.value })} placeholder="如:神陨之地" />
          </label>
          <label>
            主角名称
            <input value={d.protagonist} onChange={(e) => set({ protagonist: e.target.value })} />
          </label>
          <label>
            小说类型
            <select value={d.genre} onChange={(e) => set({ genre: e.target.value })}>
              <option value="">(未定)</option>
              {opt.小说类型.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label>
            受众定位
            <select value={d.audience} onChange={(e) => set({ audience: e.target.value })}>
              <option value="">(未定)</option>
              {opt.受众定位.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <div className="full">
            <span className="muted">核心设定/流派(可多选)</span>
            <div className="chips">
              {opt.核心设定流派.map((x) => (
                <button key={x} className={d.tropes.includes(x) ? "chip on" : "chip"} onClick={() => toggle("tropes", x)}>{x}</button>
              ))}
            </div>
          </div>
          <div className="full">
            <span className="muted">风格偏好(可多选)</span>
            <div className="chips">
              {opt.风格偏好.map((x) => (
                <button key={x} className={d.style.includes(x) ? "chip on" : "chip"} onClick={() => toggle("style", x)}>{x}</button>
              ))}
            </div>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="form">
          <label>
            情节结构
            <select value={d.plot_mode} onChange={(e) => set({ plot_mode: e.target.value })}>
              <option value="">(未定)</option>
              {opt.情节结构模式.map((x) => <option key={x.value} value={x.value}>{x.label}({x.desc})</option>)}
            </select>
          </label>
          <label>
            力量体系预设
            <select value={d.power_preset} onChange={(e) => set({ power_preset: e.target.value })}>
              <option value="">(未定)</option>
              {Object.entries(opt.力量体系).map(([cls, items]) => (
                <optgroup key={cls} label={cls}>
                  {items.map((x) => <option key={x}>{x}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <label>
            金手指预设
            <select value={d.cheat_preset} onChange={(e) => set({ cheat_preset: e.target.value })}>
              <option value="">(未定)</option>
              {opt.金手指类型.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label>
            每章字数
            <input type="number" value={d.chapter_words} onChange={(e) => set({ chapter_words: e.target.value })} placeholder="2000" />
          </label>
          <label>
            目标总字数
            <input type="number" value={d.target_words} onChange={(e) => set({ target_words: e.target.value })} placeholder="3000000" />
          </label>
          <label className="full">
            核心冲突 / 创作方向
            <textarea rows={3} value={d.core_conflict} onChange={(e) => set({ core_conflict: e.target.value })} />
          </label>
          <label className="full">
            简介
            <textarea rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} />
          </label>
        </div>
      )}

      <div className="row">
        {step === 1 ? (
          <>
            <button onClick={onCancel}>取消</button>
            <button className="primary" onClick={() => setStep(2)}>下一步</button>
          </>
        ) : (
          <>
            <button onClick={() => setStep(1)}>上一步</button>
            <button className="primary" onClick={submit} disabled={busy}>
              {busy ? "建书中…" : "建书"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
