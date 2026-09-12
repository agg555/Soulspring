import { api } from "../../api";
import type { Settings, SkillInfo } from "../../types";

/**
 * 设置页·生成口径区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 装配上限与节点正文注入 / 技能全局默认 / 大纲精修场景级显隐 / 界面自动压缩与整理官。
 * 四个分区都是"一个开关一句说明"的轻区,合在一件里;状态与落库仍留在 Settings。
 */
export default function SettingsTuning({
  s, set, setS, setError, skills, outlineError, toggleScenes, saveAssembly, saveSkills,
}: {
  s: Settings;
  set: (patch: Partial<Settings>) => void;
  setS: (v: Settings) => void;
  setError: (msg: string) => void;
  skills: SkillInfo[];
  outlineError: string;
  toggleScenes: (enabled: boolean) => void;
  saveAssembly: () => void;
  saveSkills: () => void;
}) {
  return (
    <>
      <details className="set-sec">
        <summary>装配（上限与节点正文注入）</summary>
      <p className="muted">上限=每次装配的上下文字符总额,超限先裁按需条目。</p>
      <div className="row">
        <input
          type="number"
          value={s.assembly.token_limit ?? ""}
          onChange={(e) =>
            set({
              assembly: {
                ...s.assembly,
                token_limit: e.target.value === "" ? null : Number(e.target.value),
              },
            })
          }
          placeholder="6000"
        />
        <label className="row" style={{ margin: 0, gap: 6 }} title="WPS 大纲:开启后本章祖先链与邻近子题的正文摘要(各截 300 字)按需进装配;默认关=老书行为分毫不差">
          <input
            type="checkbox"
            checked={!!s.assembly.body_inject}
            onChange={(e) =>
              set({
                assembly: { ...s.assembly, body_inject: e.target.checked },
              })
            }
          />
          节点正文进装配(默认关)
        </label>
        <button onClick={saveAssembly}>保存</button>
      </div>

      </details>
      <details className="set-sec">
        <summary>技能（全局默认）</summary>
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

      </details>
      <details className="set-sec">
        <summary>大纲精修（场景级显隐）</summary>
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

      </details>
      <details className="set-sec">
        <summary>界面（自动压缩 / 整理官开关）</summary>
      <p className="muted small">
        「工程信息开关」在对话台内(🛠 按钮,localStorage 全局偏好)。
        自动压缩:书级对话超 40 条自动把更早轮次拼成"前情提要"(纯算法零 LLM,原文全留库,
        装配改为提要+最近 16 条);默认关=全量装配(前缀缓存最省),也可在对话台点「🧹 压缩本线」手动压。
      </p>
      <div className="row">
        <label className="row">
          <input
            type="checkbox"
            checked={s.ui?.auto_compact ?? false}
            onChange={async (e) => {
              try {
                const r = await api.putUiSettings({
                  auto_compact: e.target.checked,
                  organizer_enabled: s.ui?.organizer_enabled ?? false,
                });
                setS({ ...s, ui: r.ui });
              } catch (er) { setError(String((er as Error).message || er)); }
            }}
          />
          自动压缩已{(s.ui?.auto_compact ?? false) ? "开启" : "关闭"}(点切换,即时生效)
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={s.ui?.organizer_enabled ?? false}
            onChange={async (e) => {
              try {
                const r = await api.putUiSettings({
                  auto_compact: s.ui?.auto_compact ?? false,
                  organizer_enabled: e.target.checked,
                });
                setS({ ...s, ui: r.ui });
              } catch (er) { setError(String((er as Error).message || er)); }
            }}
          />
          AI 整理官已{(s.ui?.organizer_enabled ?? false) ? "开启" : "关闭"}
          (默认关;只建议用于第三方拆书内容重排,自有内容已排版不重排)
        </label>
      </div>

      </details>
    </>
  );
}
