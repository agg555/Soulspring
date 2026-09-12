import { api } from "../../api";
import type { Settings } from "../../types";

/**
 * 设置页·触点区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 每个 AI 动作的模型/上限/追加词覆盖。注册表(reg)与已覆盖项(covered)都取自 s,
 * 未覆盖清单就地算;save 仍是"整包 PUT 后回写 s.touches"的原逻辑。
 */
export default function SettingsTouches({
  s, setS, flash, setError,
}: {
  s: Settings;
  setS: (v: Settings) => void;
  flash: (text: string) => void;
  setError: (msg: string) => void;
}) {
  return (
    <details className="set-sec">
      <summary>触点配置（每个 AI 动作的模型 / 上限 / 追加词）</summary>
      <p className="muted small">
        动作级覆盖:追加提示词(只追加不替换,插在该触点指令尾部)/模型(覆盖当前三件套,保存后请用「检测连接」验证)/输出上限。
        只存覆盖项——没列出的触点走现行为,零配置零破坏。分层:运行时手选 &gt; 触点 &gt; 默认。
      </p>
      {(() => {
        const reg = s.touches_registry ?? {};
        const covered = s.touches ?? {};
        const uncovered = Object.keys(reg).filter((k) => !covered[k]);
        const save = async (next: typeof covered) => {
          try {
            const r = await api.putTouches(next);
            setS({ ...s, touches: r.touches });
            flash("触点配置已保存");
          } catch (er) { setError(String((er as Error).message || er)); }
        };
        return (
          <>
            {Object.keys(covered).length === 0 && (
              <p className="muted small">当前无任何覆盖——全部触点走默认行为。</p>
            )}
            {Object.entries(covered).map(([k, v]) => (
              <div key={k} className="card" style={{ marginBottom: 8 }}>
                <b>{reg[k]?.label ?? k}</b>
                <span className="muted small">({k} · 默认上限 {reg[k]?.max_tokens ?? "跟随模型"})</span>
                <div className="form" style={{ marginTop: 6 }}>
                  <label>追加提示词
                    <textarea rows={2} defaultValue={v.prompt_append ?? ""}
                      onBlur={(e) => save({ ...covered, [k]: { ...v, prompt_append: e.target.value } })} />
                  </label>
                  <label>模型覆盖(留空=当前三件套)
                    <input defaultValue={v.model ?? ""} placeholder={s.llm?.model}
                      onBlur={(e) => save({ ...covered, [k]: { ...v, model: e.target.value } })} />
                  </label>
                  <label>输出上限(≥64;留空=默认)
                    <input type="number" defaultValue={v.max_tokens ?? ""} placeholder={String(reg[k]?.max_tokens ?? "")}
                      onBlur={(e) => {
                        const raw = e.target.value.trim();
                        save({ ...covered, [k]: { ...v, max_tokens: raw === "" ? undefined : Number(raw) } });
                      }} />
                  </label>
                </div>
                <button className="link" onClick={() => {
                  const next = { ...covered }; delete next[k]; save(next);
                }}>✕ 删除此覆盖</button>
              </div>
            ))}
            {uncovered.length > 0 && (
              <div className="row">
                <select defaultValue="" onChange={(e) => {
                  if (e.target.value) save({ ...covered, [e.target.value]: {} });
                }}>
                  <option value="">+ 新增触点覆盖…</option>
                  {uncovered.map((k) => (
                    <option key={k} value={k}>{reg[k]?.label ?? k}({k})</option>
                  ))}
                </select>
              </div>
            )}
          </>
        );
      })()}
    </details>
  );
}
