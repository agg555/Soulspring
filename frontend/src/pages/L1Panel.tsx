import { useEffect, useState } from "react";
import { api } from "../api";
import type { L1Category, L1Entry, L1Schema } from "../types";

const STYLE_NOTE =
  "风格指纹是 L1 特殊区:唯一写入者是文风蒸馏管道(M5 上线),此处只读展示。";

export default function L1Panel({ pid }: { pid: string }) {
  const [schema, setSchema] = useState<L1Schema | null>(null);
  const [entries, setEntries] = useState<L1Entry[]>([]);
  const [cat, setCat] = useState<string>("");
  // 编辑交互(2026-09-01 拍板):表单就地展开在条目正下方;同刻只开一个;按钮 toggle
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<Partial<L1Entry>>({});
  const [building, setBuilding] = useState(false);
  const [confirmBuild, setConfirmBuild] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => {
    api.l1List(pid).then((r) => setEntries(r.entries)).catch((e) => setError(String(e.message || e)));
  };
  useEffect(() => {
    api.l1Schema().then((s) => {
      setSchema(s);
      setCat(s.categories[0]?.key ?? "");
    }).catch((e) => setError(String(e.message || e)));
    load();
  }, [pid]);

  if (error && !schema) return <p className="error">{error}</p>;
  if (!schema) return <p className="muted">加载中…</p>;

  const cats: L1Category[] = schema.categories;
  const inCat = entries.filter((e) => e.category === cat);
  const proposals = entries.filter((e) => e.entry_status === "proposal");

  const flash = (t: string) => {
    setMsg(t);
    setTimeout(() => setMsg(""), 2500);
  };
  const reloadAll = () => {
    load();
    flash("已刷新");
  };

  const closeForms = () => {
    setEditingId(null);
    setCreating(false);
    setDraft({});
  };

  const startEdit = (e: L1Entry) => {
    setCreating(false);
    if (editingId === e.id) {   // 再点同一条 = 收起
      closeForms();
      return;
    }
    setEditingId(e.id);
    setDraft({ ...e });
  };

  const startCreate = () => {   // 新建表单仍在底部,按钮同样开/关
    if (creating) { closeForms(); return; }
    setEditingId(null);
    setDraft({ category: cat, fields: {} });
    setCreating(true);
  };

  const saveEntry = async () => {
    if (!draft.name?.trim()) {
      setError("名称必填");
      return;
    }
    try {
      if (editingId) {
        await api.l1Update(editingId, {
          name: draft.name,
          fields: draft.fields ?? {},
          notes: draft.content ?? "",
        });
      } else {
        await api.l1Create(pid, {
          category: cat,
          name: draft.name,
          fields: draft.fields ?? {},
          notes: draft.content ?? "",
        });
      }
      closeForms();
      setError("");
      reloadAll();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const approve = async (eid: string) => {
    try {
      await api.l1Approve(eid);
      flash("已批准,条目入正式档案");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };
  const reject = async (eid: string) => {
    try {
      await api.l1Delete(eid);
      flash("已驳回并移除");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const runBuild = async () => {
    setConfirmBuild(false);
    setBuilding(true);
    setError("");
    try {
      const r = await api.buildPropose(pid);
      flash(
        `AI 生成 ${r.count} 条草案入提案区` +
          (r.warning ? `;⚠ ${r.warning}` : `;本次成本 ¥${r.usage.cost_total.toFixed(4)}`)
      );
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setBuilding(false);
    }
  };

  // 编辑/新建共用表单(就地渲染:编辑跟在条目下,新建在页面底部)
  const renderForm = (isCreate: boolean) => (
    <div className="dialog">
      <h4>{isCreate ? `新建 · ${cats.find((c) => c.key === cat)?.label}` : "编辑条目"}</h4>
      <div className="form">
        <label className="full">
          名称 *
          <input
            value={draft.name ?? ""}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </label>
        {cats
          .find((c) => c.key === (draft.category ?? cat))!
          .fields.map((f) => (
            <label key={f.key} className="full">
              {f.label}
              {f.type === "textarea" ? (
                <textarea
                  rows={2}
                  value={draft.fields?.[f.key] ?? ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      fields: { ...draft.fields, [f.key]: e.target.value },
                    })
                  }
                />
              ) : (
                <input
                  value={draft.fields?.[f.key] ?? ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      fields: { ...draft.fields, [f.key]: e.target.value },
                    })
                  }
                />
              )}
            </label>
          ))}
        <label className="full">
          自由补充
          <textarea
            rows={2}
            value={draft.content ?? ""}
            onChange={(e) => setDraft({ ...draft, content: e.target.value })}
          />
        </label>
      </div>
      <div className="row">
        <button onClick={closeForms}>取消</button>
        <button className="primary" onClick={saveEntry}>保存</button>
      </div>
    </div>
  );

  return (
    <div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="row spread">
        <div className="chips">
          {cats.map((c) => (
            <button key={c.key} className={cat === c.key ? "chip on" : "chip"} onClick={() => setCat(c.key)}>
              {c.label}
            </button>
          ))}
          <button className="chip" disabled title="由蒸馏管道维护">风格指纹(只读)</button>
        </div>
        <button
          className="build-btn"
          onClick={() => setConfirmBuild(true)}
          disabled={building}
          title="仅点击时运行:调用一次模型,整套草案进提案区,人批准才入正式档案"
        >
          {building ? "AI 构建中…" : "AI 一键构建(手动)"}
        </button>
      </div>

      {confirmBuild && (
        <div className="dialog">
          <p>
            <b>确认运行 AI 一键构建?</b>仅在你确认后运行。
            将调用一次模型生成整套设定草案(预计成本几分钱),结果全部进入
            <b>提案区</b>待你逐条批准,不会直接入正式档案。
          </p>
          <div className="row">
            <button onClick={() => setConfirmBuild(false)}>取消</button>
            <button className="primary" onClick={runBuild}>运行</button>
          </div>
        </div>
      )}

      <div className="muted small">
        本类提案 {proposals.filter((p) => p.category === cat).length} 条待批准
      </div>

      <ul className="entry-list">
        {inCat.map((e) => (
          <li key={e.id} className={e.entry_status === "proposal" ? "entry proposal" : "entry"}>
            <div className="entry-head">
              <b>{e.name}</b>
              {e.entry_status === "proposal" ? (
                <span className="badge warn">AI 提案 · 待批准</span>
              ) : (
                <span className="badge ok">正式</span>
              )}
            </div>
            <dl className="entry-fields">
              {Object.entries(e.fields).map(([k, v]) => {
                const label = cats.find((c) => c.key === e.category)?.fields.find((f) => f.key === k)?.label ?? k;
                return (
                  <div key={k}>
                    <dt>{label}</dt>
                    <dd>{v}</dd>
                  </div>
                );
              })}
            </dl>
            {e.content && <p className="muted small">{e.content}</p>}
            <div className="row">
              {e.entry_status === "proposal" ? (
                <>
                  <button onClick={() => approve(e.id)}>批准入档</button>
                  <button onClick={() => reject(e.id)}>驳回</button>
                  <button onClick={() => startEdit(e)}>{editingId === e.id ? "收起" : "编辑"}</button>
                </>
              ) : (
                <>
                  <button onClick={() => startEdit(e)}>{editingId === e.id ? "收起" : "编辑"}</button>
                  <button onClick={() => reject(e.id)}>删除</button>
                </>
              )}
            </div>
            {editingId === e.id && renderForm(false)}
          </li>
        ))}
        {inCat.length === 0 && (
          <li className="muted">本类还没有条目。手工建档,或用右上角"AI 一键构建"。</li>
        )}
      </ul>

      <p className="muted small">{STYLE_NOTE}</p>

      {creating && renderForm(true)}

      <div className="row">
        <button onClick={startCreate}>{creating ? "收起新建" : "+ 手工建档"}</button>
      </div>
    </div>
  );
}
