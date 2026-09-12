import type { Settings } from "../../types";

/**
 * 设置页·模型区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 服务商切换 / 温度预设 / 模型 API 微调 / API Key 四个手风琴分区。
 * 状态与落库仍留在 Settings(照 OutputLimitsPanel 既有口径:数据下行、回调上行),
 * 故本件 props 名称与父组件局部变量逐一对齐,搬来的 JSX 一字未改。
 */
export default function SettingsModel({
  s, set, presets, tempPresets, testing, testResult, apiKey, setApiKey,
  switchProvider, switchTemp, testConnection, saveLlm, saveKey,
}: {
  s: Settings;
  set: (patch: Partial<Settings>) => void;
  presets: { key: string; label: string; model: string; key_ready: boolean; active: boolean }[];
  tempPresets: { key: string; label: string; temperature: number; top_p: number | null; active: boolean }[];
  testing: boolean;
  testResult: string;
  apiKey: string;
  setApiKey: (v: string) => void;
  switchProvider: (key: string) => void;
  switchTemp: (key: string) => void;
  testConnection: () => void;
  saveLlm: () => void;
  saveKey: () => void;
}) {
  return (
    <>
      <details className="set-sec" open>
        <summary>服务商切换（三件套一键换，免手填）</summary>
      <div className="provider-cards">
        {presets.map((ps) => (
          <button key={ps.key} className={`provider-card ${ps.active ? "on" : ""}`}
            onClick={() => switchProvider(ps.key)}
            title={ps.key_ready ? "点击切换(路由/模型/key 一并生效)" : "该商 key 未配置,先在下方 API Key 填一次"}>
            <b>{ps.label}{ps.active ? " ✓" : ""}</b>
            <span className="muted small">{ps.model}</span>
            <span className={`small ${ps.key_ready ? "ok" : "muted"}`}>
              {ps.key_ready ? "key 就绪" : "key 未配置"}
            </span>
          </button>
        ))}
        <span className="row" style={{ margin: 0 }}>
          <button disabled={testing} onClick={testConnection}>
            {testing ? "检测中…" : "🔍 检测连接(一次最小真实调用)"}
          </button>
          {testResult && <span className="small">{testResult}</span>}
        </span>
      </div>

      {/* 二期⑧:温度预设三档(用户拍板做成预设,AI 自测结论见执行记录;随时切换) */}
      </details>
      <details className="set-sec">
        <summary>温度预设（写作风格三档，一键切换）</summary>
      <div className="provider-cards">
        {tempPresets.map((tp) => (
          <button key={tp.key} className={`provider-card ${tp.active ? "on" : ""}`}
            onClick={() => switchTemp(tp.key)}
            title={tp.key === "steady" ? "0.5:用词收敛,适合精修与日常更新"
              : tp.key === "standard" ? "0.7:默认平衡(模型默认行为)"
              : "1.0 + top_p 0.95:更发散,适合开脑洞/破僵局"}>
            <b>{tp.label}{tp.active ? " ✓" : ""}</b>
            <span className="muted small">temp {tp.temperature}{tp.top_p ? ` · top_p ${tp.top_p}` : ""}</span>
          </button>
        ))}
      </div>

      </details>
      <details className="set-sec">
        <summary>模型 / API（手动微调，一般不用动）</summary>
      <div className="form">
        <label>
          名称
          <input
            value={s.llm.provider_name}
            onChange={(e) => set({ llm: { ...s.llm, provider_name: e.target.value } })}
          />
        </label>
        <label>
          Base URL(OpenAI 兼容)
          <input
            value={s.llm.base_url}
            onChange={(e) => set({ llm: { ...s.llm, base_url: e.target.value } })}
          />
        </label>
        <label>
          模型名
          <input
            value={s.llm.model}
            onChange={(e) => set({ llm: { ...s.llm, model: e.target.value } })}
          />
        </label>
        <label>
          温度
          <input
            type="number"
            step="0.1"
            value={s.llm.temperature}
            onChange={(e) =>
              set({ llm: { ...s.llm, temperature: Number(e.target.value) } })
            }
          />
        </label>
        <label>
          max_tokens
          <input
            type="number"
            value={s.llm.max_tokens}
            onChange={(e) => set({ llm: { ...s.llm, max_tokens: Number(e.target.value) } })}
          />
        </label>
        <button onClick={saveLlm}>保存模型配置</button>
      </div>

      </details>
      <details className="set-sec">
        <summary>API Key</summary>
      <p className="muted">
        {s.api_key_set ? "已配置(不回显)。重新填写即覆盖。" : "未配置。key 存本地 secrets 文件,不入 git。"}
      </p>
      <div className="row">
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-…"
        />
        <button onClick={saveKey}>保存 Key</button>
      </div>

      </details>
    </>
  );
}
