import { useState } from "react";
import { api } from "../api";
import type { ReferencePrompts, RefPromptItem } from "../types";
import RefPromptPicker from "./RefPromptPicker";
import { uiConfirm } from "./uiConfirm";

// 可绑定参考提示词的触点(=长文本生成入口;与后端接入点一致)
const BINDABLE_ACTIONS = ["chapter_draft", "chapter_repair", "outline_body_suggest",
  "outline_subtopic_split", "build_proposal"];

/**
 * 参考提示词库面板(2026-09-09 拍板;2026-09-10 用户反馈:触点绑定改多选、
 * 全中文标签)。库 CRUD(搜索)+ 三层绑定(全局 / 触点多选 / 按书)。
 */
export default function RefPromptsPanel({ rp, books, registry, flash, onChanged }: {
  rp: ReferencePrompts;
  books: { id: string; name: string }[];
  registry: Record<string, { label?: string; kind?: string; hosts?: string; max_tokens?: number | null }>;
  flash: (t: string) => void;
  onChanged: (fresh: ReferencePrompts) => void;
}) {
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<RefPromptItem | null>(null);
  const [bindActions, setBindActions] = useState<string[]>([]);   // 多选触点
  const [applyIds, setApplyIds] = useState<string[]>([]);         // 应用到选中触点的提示词
  const [bindBook, setBindBook] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cn = (a: string) => registry?.[a]?.label ?? a;

  const save = async (next: ReferencePrompts) => {
    setBusy(true);
    setError("");
    try {
      const r = await api.putReferencePrompts({
        items: next.items,
        global_bind: next.global_bind,
        actions: next.actions,
        books: next.books,
      });
      onChanged(r.reference_prompts);
      flash("参考提示词已保存");
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  const shown = rp.items.filter((i) =>
    !q.trim() || i.name.includes(q.trim()) || i.text.includes(q.trim()));

  if (editing) {
    return (
      <div>
        <h3>📚 编辑参考提示词</h3>
        <div className="form">
          <label>名称
            <input value={editing.name} maxLength={30}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
          </label>
          <label className="full">内容(注入给 AI 作参考;上限 10000 字)
            <textarea rows={8} value={editing.text} maxLength={10000}
              onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
          </label>
        </div>
        <div className="row">
          <button className="primary" disabled={busy}
            onClick={() => {
              if (!editing.name.trim()) { setError("名称不能为空"); return; }
              if (!editing.text.trim()) { setError("内容不能为空"); return; }
              const exists = rp.items.some((i) => i.id === editing.id);
              void save({ ...rp, items: exists
                ? rp.items.map((i) => (i.id === editing.id ? editing : i))
                : [...rp.items, editing] }).then(() => setEditing(null));
            }}>保存</button>
          <button onClick={() => setEditing(null)}>取消</button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  return (
    <div>
      <p className="muted small">
        供长文本生成入口(章节草稿/自修/正文建议/子题拆分/构建提案)挂载的参考条目;
        注入时标注「仅作参考」。绑定生效层:运行时手选 &gt; 按书 &gt; 按触点 &gt; 全局。
      </p>
      <div className="row">
        <input placeholder="🔍 搜索提示词…" value={q}
          onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
        <button disabled={busy} onClick={() => setEditing({
          id: `rp_${Date.now().toString(36)}`, name: "", text: "",
        })}>+ 新建</button>
      </div>
      <ul className="entry-list">
        {shown.length === 0 && <li className="muted small">(还没有提示词条目)</li>}
        {shown.map((i) => (
          <li key={i.id} className="entry entry-head">
            <b>{i.name}</b>
            <span className="muted small" style={{ flex: 1 }}>
              {i.text.slice(0, 60)}{i.text.length > 60 ? "…" : ""}
            </span>
            <button className="link" onClick={() => setEditing({ ...i })}>编辑</button>
            <button className="link danger-link" disabled={busy}
              onClick={async () => {
                if (await uiConfirm(`删除提示词「${i.name}」?(各层绑定引用一并移除)`)) {
                  void save({
                    ...rp,
                    items: rp.items.filter((x) => x.id !== i.id),
                    global_bind: rp.global_bind.filter((x) => x !== i.id),
                    actions: Object.fromEntries(
                      Object.entries(rp.actions).map(([k, v]) => [k, v.filter((x) => x !== i.id)])),
                    books: Object.fromEntries(
                      Object.entries(rp.books).map(([k, v]) => [k, v.filter((x) => x !== i.id)])),
                  });
                }
              }}>删</button>
          </li>
        ))}
      </ul>

      <h4 style={{ marginBottom: 4 }}>绑定</h4>
      <div className="row" style={{ margin: "4px 0" }}>
        <b className="small">全局默认:</b>
        <RefPromptPicker items={rp.items} selected={rp.global_bind}
          onChange={(ids) => void save({ ...rp, global_bind: ids })} />
        <span className="muted small">{rp.global_bind.length} 条</span>
      </div>
      <div className="row" style={{ margin: "4px 0", flexWrap: "wrap" }}>
        <b className="small">按触点(可多选):</b>
        <span className="row" style={{ gap: 8, flexWrap: "wrap", margin: 0 }}>
          {BINDABLE_ACTIONS.map((a) => {
            const n = (rp.actions?.[a] ?? []).length;
            const on = bindActions.includes(a);
            return (
              <label key={a} className="row" style={{ gap: 4, margin: 0, cursor: "pointer" }}>
                <input type="checkbox" checked={on}
                  onChange={() => setBindActions(
                    on ? bindActions.filter((x) => x !== a) : [...bindActions, a])} />
                {cn(a)}
                <span className="muted small">({n} 条)</span>
              </label>
            );
          })}
        </span>
      </div>
      {bindActions.length > 0 && (
        <div className="row" style={{ margin: "4px 0" }}>
          <span className="muted small">
            已选 {bindActions.length} 个触点,选择要应用的提示词:
          </span>
          <RefPromptPicker items={rp.items} selected={applyIds} onChange={setApplyIds} />
          <button className="primary" disabled={busy}
            title="把选中的提示词写入所有勾选的触点绑定(不选提示词=清除这些触点的绑定)"
            onClick={() => {
              const nextActions = { ...(rp.actions ?? {}) };
              for (const a of bindActions) {
                if (applyIds.length) nextActions[a] = applyIds;
                else delete nextActions[a];
              }
              void save({ ...rp, actions: nextActions }).then(() => {
                setBindActions([]);
                setApplyIds([]);
              });
            }}>应用到选中触点</button>
        </div>
      )}
      <div className="row" style={{ margin: "4px 0" }}>
        <b className="small">按书:</b>
        <select value={bindBook} onChange={(e) => setBindBook(e.target.value)}>
          <option value="">(选书)</option>
          {books.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        {bindBook && (
          <>
            <RefPromptPicker items={rp.items} selected={rp.books?.[bindBook] ?? []}
              onChange={(ids) => void save({ ...rp,
                books: { ...(rp.books ?? {}), [bindBook]: ids } })} />
            <span className="muted small">
              {(rp.books?.[bindBook] ?? []).length} 条(本书所有长文本生成默认携带)
            </span>
          </>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
