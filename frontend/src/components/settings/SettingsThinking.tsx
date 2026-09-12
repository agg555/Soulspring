import type { Settings, ThinkingLevel } from "../../types";

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

/**
 * 设置页·思考档位区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 按动作分档的省预算闸门;ACTION_LABELS 只服务本表,故随本件安家。
 */
export default function SettingsThinking({
  s, set, saveThinking,
}: {
  s: Settings;
  set: (patch: Partial<Settings>) => void;
  saveThinking: () => void;
}) {
  return (
    <details className="set-sec">
      <summary>思考档位（省预算闸门）</summary>
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
    </details>
  );
}
