import { useEffect, useState } from "react";
import { api } from "../api";
import type { Settings, SkillInfo } from "../types";
import OutputLimitsPanel from "../components/OutputLimitsPanel";
import RefPromptsPanel from "../components/RefPromptsPanel";
import SettingsAbout from "../components/settings/SettingsAbout";
import SettingsMaintenance from "../components/settings/SettingsMaintenance";
import SettingsModel from "../components/settings/SettingsModel";
import SettingsPricing from "../components/settings/SettingsPricing";
import SettingsThinking from "../components/settings/SettingsThinking";
import SettingsTouches from "../components/settings/SettingsTouches";
import SettingsTuning from "../components/settings/SettingsTuning";

/**
 * 设置页(薄壳)。
 * 大文件拆分批(2026-09-10,纯 JSX 搬动零行为变化):17 个手风琴分区的渲染搬去
 * components/settings/ 下按域分件(模型/价格/思考/装配技能大纲界面/触点/备份 MCP/关于),
 * 状态、取数 effect 与全部落库 handler 一律留在本文件——照 OutputLimitsPanel
 * 既有口径"数据下行、回调上行",子件 props 与本地变量同名故搬去的 JSX 一字未改。
 * 注意:Hooks 必须都在下面两个条件 return 之前(React #310 白屏,本组件有前科)。
 */
export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [mcpJson, setMcpJson] = useState("");
  const [mcpError, setMcpError] = useState("");   // 导入报错就地显示,不打没整页
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  // 大纲精修(C1):场景显隐开关;局部错误态(不早退整页)——Hooks 必须在条件 return 之前
  const [outlineError, setOutlineError] = useState("");
  // 模型切换器(体感 2026-09-06):服务商预设卡+一键切换+检测连接
  const [tempPresets, setTempPresets] = useState<{ key: string; label: string;
    temperature: number; top_p: number | null; active: boolean }[]>([]);
  const loadTemps = () =>
    api.temperaturePresets().then((r) => setTempPresets(r.presets)).catch(() => {});
  const [presets, setPresets] = useState<{ key: string; label: string; model: string;
    key_ready: boolean; active: boolean }[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string>("");
  // 书列表(输出上下限/参考提示词面板的按书维度)
  const [bookRows, setBookRows] = useState<{ id: string; name: string }[]>([]);
  // 备份按钮(候选清单落地批 B):snap=快照中 push=推送中;结果走 flash/error
  const [backupBusy, setBackupBusy] = useState<"" | "snap" | "push">("");
  useEffect(() => {
    api.llmPresets().then((r) => setPresets(r.presets)).catch(() => {});
    loadTemps();
  }, []);

  useEffect(() => {
    api.settings().then(setS).catch((e) => setError(String(e.message || e)));
    api.reviewSkills().then((r) => setSkills(r.skills)).catch(() => setSkills([]));
    api.overview().then((o) => setBookRows(
      o.projects.map((p) => ({ id: p.id, name: p.name })).filter((b) => !b.name.startsWith("__")),
    )).catch(() => {});
  }, []);

  if (error) return <div><h2>设置</h2><p className="error">{error}</p></div>;
  if (!s) return <div><h2>设置</h2><p className="muted">加载中…</p></div>;

  const set = (patch: Partial<Settings>) => setS({ ...s, ...patch });
  const flash = (text: string) => {
    setMsg(text);
    setTimeout(() => setMsg(""), 2500);
  };

  const switchProvider = async (key: string) => {
    setError("");
    try {
      const r = await api.llmSwitch(key);
      setS({ ...s, llm: { ...s.llm, ...r.llm } });
      setPresets((cur) => cur.map((x) => ({ ...x, active: x.key === key })));
      flash(`已切换到 ${key},三件套(路由/模型/key)一并生效`);
      setTestResult("");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const switchTemp = async (key: string) => {
    setError("");
    try {
      const r = await api.putTemperaturePreset(key);
      setS({ ...s, llm: { ...s.llm, temperature: r.preset.temperature, top_p: r.preset.top_p } });
      setTempPresets((cur) => cur.map((x) => ({ ...x, active: x.key === key })));
      flash(`温度预设:${r.preset.label}(temp ${r.preset.temperature}`
        + (r.preset.top_p ? ` · top_p ${r.preset.top_p})` : ")"));
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const testConnection = async () => {
    setTesting(true);
    setTestResult("");
    try {
      const r = await api.llmTest();
      setTestResult(r.ok
        ? `✓ 连通(${r.model});回包「${r.reply || "(思考未溢出)"}」`
        : `✗ ${r.error ?? "失败"}`);
    } catch (e: unknown) {
      setTestResult(`✗ ${String((e as Error).message || e)}`);
    } finally {
      setTesting(false);
    }
  };

  const saveLlm = async () => {
    try {
      const r = await api.putLlm(s.llm);
      setS({ ...s, llm: r.llm });
      flash("模型配置已保存,即时生效");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const savePricing = async () => {
    try {
      await api.putPricing({ default: s.pricing.default, models: s.pricing.models,
        standard: s.pricing.standard ?? null, discount_until: s.pricing.discount_until ?? "" });
      flash("价格基准已保存,即时生效");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const saveKey = async () => {
    if (!apiKey.trim()) return;
    try {
      await api.putApiKey(apiKey.trim());
      setApiKey("");
      set({ api_key_set: true });
      flash("API key 已保存(本地 secrets 文件,不入 git)");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const saveAssembly = async () => {
    try {
      await api.putAssembly({
        token_limit: s.assembly.token_limit,
        body_inject: !!s.assembly.body_inject,
      });
      flash("装配设置已保存,即时生效");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const saveThinking = async () => {
    try {
      const r = await api.putThinking({
        enabled: s.thinking.enabled,
        model_match: s.thinking.model_match,
        default: s.thinking.default,
        by_action: s.thinking.by_action,
      });
      setS({ ...s, thinking: r.thinking });
      flash("思考档位已保存,即时生效");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const saveSkills = async () => {
    try {
      const r = await api.putSkills(s.skills.global_default);
      setS({ ...s, skills: r.skills });
      flash("全局默认技能已保存,下次生成生效");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  // 大纲精修(C1):场景显隐开关;局部错误态(不早退整页)
  const toggleScenes = async (enabled: boolean) => {
    setOutlineError("");
    try {
      const r = await api.putOutlineSettings({ scenes_enabled: enabled });
      setS({ ...s, outline: r.outline });
      flash(enabled
        ? "场景级已开启:大纲树可建五字段场景(场景不进状态机)"
        : "场景级已关闭:大纲树回到四级显示(场景数据保留)");
    } catch (e: unknown) {
      setOutlineError(String((e as Error).message || e));
    }
  };

  const toggleServer = async (index: number, enabled: boolean) => {
    const servers = s.mcp.servers.map((srv, i) => (i === index ? { ...srv, enabled } : srv));
    try {
      const r = await api.putMcpServers(servers);
      setS({ ...s, mcp: r.mcp });
      setMcpError("");
      flash("已更新(本期仅存配置,不实际建连)");
    } catch (e: unknown) {
      setMcpError(String((e as Error).message || e));
    }
  };

  const removeServer = async (index: number) => {
    const servers = s.mcp.servers.filter((_, i) => i !== index);
    try {
      const r = await api.putMcpServers(servers);
      setS({ ...s, mcp: r.mcp });
      setMcpError("");
      flash("已删除");
    } catch (e: unknown) {
      setMcpError(String((e as Error).message || e));
    }
  };

  const importMcp = async () => {
    setMcpError("");
    try {
      const r = await api.importMcp(mcpJson);
      setS({ ...s, mcp: r.mcp });
      setMcpJson("");
      flash(`已导入 ${r.imported} 条${r.warnings?.length ? `;${r.warnings.length} 条被跳过` : ""}${r.note ? `。${r.note}` : ""}`);
    } catch (e: unknown) {
      setMcpError(String((e as Error).message || e));
    }
  };

  const patchDefaultPrice = (field: "input_per_m" | "output_per_m", value: string) => {
    set({
      pricing: { ...s.pricing, default: { ...s.pricing.default, [field]: Number(value) || 0 } },
    });
  };
  const patchStandardPrice = (field: "input_per_m" | "output_per_m", value: string) => {
    const std = s.pricing.standard ?? { input_per_m: 0, output_per_m: 0 };
    set({ pricing: { ...s.pricing, standard: { ...std, [field]: Number(value) || 0 } } });
  };
  const patchDiscountUntil = (value: string) => {
    set({ pricing: { ...s.pricing, discount_until: value } });
  };

  return (
    <div>
      <h2>设置</h2>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="row" style={{ margin: "8px 0" }}>
        <button className="link" onClick={() => document.querySelectorAll<HTMLDetailsElement>(".set-sec").forEach((d) => { d.open = true; })}>全部展开</button>
        <button className="link" onClick={() => document.querySelectorAll<HTMLDetailsElement>(".set-sec").forEach((d) => { d.open = false; })}>全部收起</button>
        <span className="muted small">点标题展开对应设置</span>
      </div>

      <SettingsModel
        s={s} set={set} presets={presets} tempPresets={tempPresets}
        testing={testing} testResult={testResult} apiKey={apiKey} setApiKey={setApiKey}
        switchProvider={switchProvider} switchTemp={switchTemp}
        testConnection={testConnection} saveLlm={saveLlm} saveKey={saveKey} />
      <SettingsPricing
        s={s} patchDefaultPrice={patchDefaultPrice}
        patchStandardPrice={patchStandardPrice} patchDiscountUntil={patchDiscountUntil}
        savePricing={savePricing} />
      <SettingsThinking s={s} set={set} saveThinking={saveThinking} />
      <SettingsTuning
        s={s} set={set} setS={setS} setError={setError} skills={skills}
        outlineError={outlineError} toggleScenes={toggleScenes}
        saveAssembly={saveAssembly} saveSkills={saveSkills} />
      <SettingsTouches
        s={s} setS={setS} flash={flash} setError={setError} />

      <details className="set-sec">
        <summary>输出上下限（全部 AI 触点）</summary>
        <div className="set-pad"><OutputLimitsPanel s={s} flash={flash} onChanged={(fresh) => setS(fresh)} /></div>
      </details>
      <details className="set-sec">
        <summary>参考提示词库</summary>
        <div className="set-pad"><RefPromptsPanel rp={s.reference_prompts ?? { items: [], global_bind: [], actions: {}, books: {} }}
          books={bookRows} registry={s.touches_registry ?? {}} flash={flash}
          onChanged={(fresh) => setS({ ...s, reference_prompts: fresh })} /></div>
      </details>

      <SettingsMaintenance
        s={s} backupBusy={backupBusy} setBackupBusy={setBackupBusy}
        flash={flash} setError={setError}
        mcpJson={mcpJson} setMcpJson={setMcpJson} mcpError={mcpError}
        toggleServer={toggleServer} removeServer={removeServer} importMcp={importMcp} />
      <SettingsAbout />
    </div>
  );
}
