import { useState } from "react";
import type { PromptTemplate } from "../types";

/**
 * 选择填空式预设模板(2026-09-09 拍板:"弹出一个框几条信息,在下面回复栏填入,
 * 可自定义问题;之前的优化/奇思妙想也是这个样子"):
 * - 模板=问题清单;点 chip 弹填空表单,作者逐条作答(可留空跳过),确认即发送;
 * - 答案组装成 preset_text 注入 system(与内置 preset 协议段叠加);
 * - 内置模板(优化/奇思妙想)问题固定;用户模板存 settings.prompt_templates,
 *   管理弹窗增删改,全部 AI 对话宿主共用。
 */

// 内置模板的问题定义(无定义的 preset 保持老点击行为,如书级方向卡)
export const TEMPLATE_QUESTIONS: Record<string, string[]> = {
  optimize: [
    "要优化什么?(如:某段节奏 / 对话 / 描写 / 整体结构)",
    "希望往哪个方向改?(例:更快进入冲突、加强代入感)",
    "有什么必须保留的?(可空)",
  ],
  ideas: [
    "围绕什么发散?(本节点设定 / 某角色 / 某冲突)",
    "点子要稳还是野?(稳健可用 / 大胆放飞)",
    "有没有不能碰的约束?(可空)",
  ],
};

export interface FillChip {
  key: string;          // 内置=preset key;自定义=模板 id
  name: string;
  builtin: boolean;
  questions: string[];
}

export function fillTemplateText(questions: string[], answers: string[]): string {
  return questions
    .map((q, i) => ({ q, a: (answers[i] ?? "").trim() }))
    .filter((x) => x.a)
    .map((x) => `- ${x.q}:${x.a}`)
    .join("\n");
}

/** 填空表单:点模板 chip 后弹出;全留空确认=只带模板协议段(兼容老"选完自己写")。 */
export function TemplateFillDialog({ chip, busy, onSend, onClose }: {
  chip: FillChip;
  busy?: boolean;
  onSend: (answers: string[]) => void;
  onClose: () => void;
}) {
  const [answers, setAnswers] = useState<string[]>(() => chip.questions.map(() => ""));
  return (
    <div className="dialog tpl-fill">
      <p><b>模板:{chip.name}</b>(填空后发送;留空的项跳过,全部留空=只带模板指令自由发挥)</p>
      {chip.questions.map((q, i) => (
        <label key={i} className="full">
          {q}
          <input
            autoFocus={i === 0}
            value={answers[i]}
            placeholder="在这里填…"
            onChange={(e) => setAnswers(answers.map((a, j) => (j === i ? e.target.value : a)))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend(answers);
              }
            }}
          />
        </label>
      ))}
      <div className="row">
        <button className="primary" disabled={!!busy} onClick={() => onSend(answers)}>
          发送
        </button>
        <button onClick={onClose}>取消</button>
      </div>
    </div>
  );
}

/** 模板管理:列表/新建/编辑(名称+问题清单增删改)/删除;保存=全量替换。 */
export function TemplateManagerDialog({ templates, onSave, onClose }: {
  templates: PromptTemplate[];
  onSave: (items: PromptTemplate[]) => Promise<void>;
  onClose: () => void;
}) {
  const [list, setList] = useState<PromptTemplate[]>(() =>
    templates.map((t) => ({ ...t, questions: [...t.questions] })));
  const [editing, setEditing] = useState<PromptTemplate | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await onSave(list);
      onClose();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    const patch = (p: Partial<PromptTemplate>) => setEditing({ ...editing, ...p });
    return (
      <div className="dialog tpl-fill">
        <p><b>编辑模板</b></p>
        <label className="full">
          模板名称
          <input value={editing.name} maxLength={30}
            placeholder="如:查时间线矛盾"
            onChange={(e) => patch({ name: e.target.value })} />
        </label>
        <p className="muted small">问题清单(作者逐条填空;留空的问题项保存时剔除,至少一条):</p>
        {editing.questions.map((q, i) => (
          <div className="row" key={i} style={{ margin: "3px 0" }}>
            <input style={{ flex: 1 }} maxLength={120} value={q}
              placeholder={`问题 ${i + 1},如:道具希望什么方式优化?`}
              onChange={(e) => patch({
                questions: editing.questions.map((x, j) => (j === i ? e.target.value : x)),
              })} />
            <button className="link danger-link" onClick={() => patch({
              questions: editing.questions.filter((_, j) => j !== i),
            })}>删</button>
          </div>
        ))}
        <div className="row">
          <button className="link" onClick={() => patch({ questions: [...editing.questions, ""] })
            }>+ 加一条问题</button>
        </div>
        <div className="row">
          <button className="primary" onClick={() => {
            const name = editing.name.trim();
            if (!name) { setError("模板名称不能为空"); return; }
            const qs = editing.questions.map((q) => q.trim()).filter(Boolean);
            if (qs.length === 0) { setError("至少要有一条问题"); return; }
            const saved = { ...editing, name, questions: qs };
            // 新建的 id 不在 list 里=新增;已存在=就地替换
            setList(list.some((t) => t.id === editing.id)
              ? list.map((t) => (t.id === editing.id ? saved : t))
              : [...list, saved]);
            setEditing(null);
          }}>完成编辑</button>
          <button onClick={() => setEditing(null)}>取消</button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  return (
    <div className="dialog tpl-fill">
      <p><b>我的模板</b>(全部 AI 对话入口共用;点模板 chip 填空即发送)</p>
      {list.length === 0 && <p className="muted small">还没有自定义模板。</p>}
      <ul className="entry-list">
        {list.map((t) => (
          <li key={t.id} className="entry entry-head">
            <b>{t.name}</b>
            <span className="muted small">{t.questions.length} 问</span>
            <button className="link" onClick={() => setEditing({ ...t, questions: [...t.questions] })
              }>编辑</button>
            <button className="link danger-link"
              onClick={() => setList(list.filter((x) => x.id !== t.id))}>删</button>
          </li>
        ))}
      </ul>
      <div className="row">
        <button className="link" onClick={() => setEditing({
          id: `tpl_${Date.now().toString(36)}`,
          name: "",
          questions: [""],
        })}>+ 新建模板</button>
        <span style={{ flex: 1 }} />
        <button className="primary" disabled={busy} onClick={save}>保存全部</button>
        <button onClick={onClose}>关闭</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
