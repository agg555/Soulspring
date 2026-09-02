import { useEffect, useState } from "react";
import { api } from "../api";
import type { Settings, SkillInfo, ThinkingLevel } from "../types";

// 动作 -> 中文说明;顺序按"机械活在前、创作活在后"排列,便于一眼看出分档意图
const ACTION_LABELS: { action: string; label: string }[] = [
  { action: "chaishu_summary", label: "拆书章节摘要(机械提取)" },
  { action: "l2_rewrite_draft", label: "L2 回写 diff 起草(机械提取)" },
  { action: "chapter_normalize", label: "字数规整(±20% 压扩)" },
  { action: "chat_test", label: "连通性测试" },
  { action: "chapter_plan", label: "写章计划卡(创作)" },
  { action: "chapter_draft", label: "章节草稿(创作核心)" },
  { action: "chapter_repair", label: "审计后 AI 自修(创作)" },
  { action: "chapter_review", label: "LLM 层评审(审美判断)" },
  { action: "review_chat", label: "审稿对话台(审美判断)" },
  { action: "build_proposal", label: "一键构建提案(长 JSON)" },
];

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

  useEffect(() => {
    api.settings().then(setS).catch((e) => setError(String(e.message || e)));
    api.reviewSkills().then((r) => setSkills(r.skills)).catch(() => setSkills([]));
  }, []);

  if (error) return <div><h2>设置</h2><p className="error">{error}</p></div>;
  if (!s) return <div><h2>设置</h2><p className="muted">加载中…</p></div>;

  const set = (patch: Partial<Settings>) => setS({ ...s, ...patch });
  const flash = (text: string) => {
    setMsg(text);
    setTimeout(() => setMsg(""), 2500);
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
      await api.putPricing({ default: s.pricing.default, models: s.pricing.models });
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
      await api.putAssembly(s.assembly.token_limit);
      flash("装配上限占位已保存(M3 定数值)");
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

  return (
    <div>
      <h2>设置</h2>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <h3>模型 / API</h3>
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

      <h3>API Key</h3>
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

      <h3>价格基准(元 / 百万 token)</h3>
      <div className="form">
        <label>
          默认输入价
          <input
            type="number"
            step="0.01"
            value={s.pricing.default.input_per_m}
            onChange={(e) => patchDefaultPrice("input_per_m", e.target.value)}
          />
        </label>
        <label>
          默认输出价
          <input
            type="number"
            step="0.01"
            value={s.pricing.default.output_per_m}
            onChange={(e) => patchDefaultPrice("output_per_m", e.target.value)}
          />
        </label>
        <button onClick={savePricing}>保存价格基准</button>
      </div>
      <p className="muted">
        单章预算告警线:¥{s.budget.per_chapter_alert}(任务书 §6)。0.25 元线的标定依赖真实价格,运行期校准。
      </p>

      <h3>思考档位(省预算闸门)</h3>
      <p className="muted">
        GLM-5.3 系模型强制思考、<strong>思考 token 按输出价计费</strong>。实测同一任务 low 档比默认档省约
        90%、快约 6 倍。这里按动作分档:机械活用 low,创作与审美活用 max。
      </p>
      <div className="form">
        <label className="row">
          <input
            type="checkbox"
            checked={s.thinking.enabled}
            onChange={(e) =>
              set({ thinking: { ...s.thinking, enabled: e.target.checked } })
            }
          />
          启用按动作分档(关掉则回到模型原生行为)
        </label>
        <label>
          模型匹配串(只对匹配的模型注入)
          <input
            value={s.thinking.model_match}
            onChange={(e) =>
              set({ thinking: { ...s.thinking, model_match: e.target.value } })
            }
          />
        </label>
        <label>
          未列出动作的默认档位
          <select
            value={s.thinking.default}
            onChange={(e) =>
              set({
                thinking: {
                  ...s.thinking,
                  default: e.target.value as ThinkingLevel,
                },
              })
            }
          >
            <option value="low">low(便宜快跑)</option>
            <option value="high">high(均衡)</option>
            <option value="max">max(深度思考)</option>
          </select>
        </label>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>动作</th>
            <th>说明</th>
            <th>档位</th>
          </tr>
        </thead>
        <tbody>
          {ACTION_LABELS.map(({ action, label }) => (
            <tr key={action}>
              <td><code>{action}</code></td>
              <td className="muted">{label}</td>
              <td>
                <select
                  value={s.thinking.by_action[action] ?? s.thinking.default}
                  onChange={(e) =>
                    set({
                      thinking: {
                        ...s.thinking,
                        by_action: {
                          ...s.thinking.by_action,
                          [action]: e.target.value as ThinkingLevel,
                        },
                      },
                    })
                  }
                >
                  <option value="low">low</option>
                  <option value="high">high</option>
                  <option value="max">max</option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={saveThinking}>保存思考档位</button>
      <p className="muted">
        只可 low / high / max——该模型不支持关闭思考。llm.extra 里若显式写了
        reasoning_effort,以 extra 为准。
      </p>

      <h3>装配 token 上限(占位)</h3>
      <p className="muted">数值由任务书挂账 #5,M3 装配预览硬编码前定;此处仅存占位。</p>
      <div className="row">
        <input
          type="number"
          value={s.assembly.token_limit ?? ""}
          onChange={(e) =>
            set({
              assembly: {
                token_limit: e.target.value === "" ? null : Number(e.target.value),
              },
            })
          }
          placeholder="未定"
        />
        <button onClick={saveAssembly}>保存占位</button>
      </div>

      <h3>技能(全局默认)</h3>
      <p className="muted">
        正文生成(工作台草稿/自修)的默认注入技能;单本书可在其「书籍信息」页覆盖。
        优先级:运行时手选 &gt; 单本书 &gt; 全局 &gt; 不启用。技能文档来自 prompts\技能\。
      </p>
      <div className="row">
        <select
          value={s.skills.global_default}
          onChange={(e) => set({ skills: { ...s.skills, global_default: e.target.value } })}
        >
          <option value="">(不启用技能)</option>
          {skills.map((sk) => (
            <option key={sk.key} value={sk.key}>{sk.name}</option>
          ))}
        </select>
        <button onClick={saveSkills}>保存技能默认</button>
      </div>

      <h3>大纲精修(场景级显隐)</h3>
      <p className="muted">
        开启后大纲树可建「场景(beat)」节点(挂章下,固定五字段:场景目标/冲突/出口钩子/
        出场角色/预计字数;场景不进章节状态机)。关闭时树与四级现状一致,场景数据保留。
      </p>
      {outlineError && <p className="error">{outlineError}</p>}
      <div className="row">
        <label className="row">
          <input
            type="checkbox"
            checked={s.outline?.scenes_enabled ?? false}
            onChange={(e) => toggleScenes(e.target.checked)}
          />
          场景级已{(s.outline?.scenes_enabled ?? false) ? "开启" : "关闭"}(点切换,即时生效)
        </label>
      </div>

      <h3>MCP 服务器(预留区,本期不建连)</h3>
      <p className="muted">
        只做配置存取与展示;启用开关也仅是配置位——实际连接要等 M5 SDK 白名单制查证基座接通。
        命令行型(stdio)最终仍受任务书 §3 命令白名单约束。
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>传输</th>
            <th>目标(URL / 命令)</th>
            <th>启用</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {s.mcp.servers.map((srv, i) => (
            <tr key={srv.name}>
              <td><code>{srv.name}</code></td>
              <td>{srv.transport ?? "stdio"}</td>
              <td className="muted small">
                {srv.url ?? [srv.command, ...(srv.args ?? [])].join(" ")}
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={srv.enabled}
                  onChange={(e) => toggleServer(i, e.target.checked)}
                />
              </td>
              <td><button className="link" onClick={() => removeServer(i)}>删</button></td>
            </tr>
          ))}
          {s.mcp.servers.length === 0 && (
            <tr><td colSpan={5} className="muted">暂无服务端,用下方 JSON 导入。</td></tr>
          )}
        </tbody>
      </table>

      <h4>导入 mcpServers JSON</h4>
      <p className="muted">
        兼容通用格式:{"{"}"mcpServers": {"{"} 名称: {"{"}command, args, env{"}"} 或 {"{"}url, headers{"}"} {"}"}{"}"}。
        敏感字段(key / token / authorization / api_key)会自动剥离进本地 secrets 文件,不入库不入 git;
        导入的服务端默认为「停用」。非法 JSON 会在上方报错,不会半写。
      </p>
      <textarea
        rows={6}
        value={mcpJson}
        onChange={(e) => setMcpJson(e.target.value)}
        placeholder={'{\n  "mcpServers": {\n    "fetch": { "command": "mcp-server-fetch", "args": [] },\n    "docs": { "url": "http://127.0.0.1:8722/mcp", "headers": { "Authorization": "Bearer sk-…" } }\n  }\n}'}
      />
      {mcpError && <p className="error">{mcpError}</p>}
      <div className="row">
        <button onClick={importMcp} disabled={!mcpJson.trim()}>解析并导入</button>
      </div>
    </div>
  );
}
