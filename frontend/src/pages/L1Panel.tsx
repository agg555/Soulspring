import { useEffect, useState, type ReactElement } from "react";
import { api } from "../api";
import type { L1Category, L1Entry, L1Schema } from "../types";
import ChatPanel from "../components/ChatPanel";
import NamingStudio from "../components/NamingStudio";
import { uiConfirm } from "../components/uiConfirm";

const STYLE_NOTE =
  "风格指纹是 L1 特殊区:唯一写入者是文风蒸馏管道(M5 上线),此处只读展示。";

export default function L1Panel({ pid, onShowLinks }: {
  pid: string;
  onShowLinks?: (etype: string, nid: string, title: string) => void;   // B3 互链
}) {
  const [schema, setSchema] = useState<L1Schema | null>(null);
  const [entries, setEntries] = useState<L1Entry[]>([]);
  const [cat, setCat] = useState<string>("");
  // 编辑交互(2026-09-01 拍板):表单就地展开在条目正下方;同刻只开一个;按钮 toggle
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<Partial<L1Entry>>({});
  const [building, setBuilding] = useState(false);
  const [buildStage, setBuildStage] = useState("");
  const [confirmBuild, setConfirmBuild] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [aiBusy, setAiBusy] = useState<string | null>(null);
  // 折叠记忆(树形化后大设定可收起;localStorage 按书持久)
  const [folded, setFolded] = useState<Set<string>>(new Set());

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

  const startCreate = (parentId: string | null) => {   // 新建表单就地,按钮开/关
    if (creating && (draft.parent_entry_id ?? null) === parentId) { closeForms(); return; }
    setEditingId(null);
    setDraft({ category: cat, fields: {}, parent_entry_id: parentId });
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
          category: draft.category ?? cat,
          name: draft.name,
          fields: draft.fields ?? {},
          notes: draft.content ?? "",
          parent_entry_id: draft.parent_entry_id ?? null,
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

  // 批次二 AI 流升级:构建任务化(阶段进度/切页签不丢/完成回填)
  const runBuild = async () => {
    setConfirmBuild(false);
    setBuilding(true);
    setError("");
    try {
      const { task } = await api.buildProposeAsync(pid);
      const poll = window.setInterval(async () => {
        try {
          const r = await api.activeGenTasks();
          const t = r.tasks.find((x) => x.id === task.id);
          if (!t) return;   // 列表偶发未含,下轮再看
          setBuildStage(t.stage === "calling" ? "调用模型" : t.stage === "parsing" ? "解析草案" : t.stage);
          if (t.status === "done") {
            window.clearInterval(poll);
            const count = (t.result as { count?: number } | null)?.count ?? "?";
            flash(`AI 生成 ${count} 条草案入提案区;本次成本 ¥${(t.usage_total ?? 0).toFixed(4)}`);
            setBuilding(false);
            setBuildStage("");
            load();
          } else if (t.status === "error") {
            window.clearInterval(poll);
            setError(t.error ?? "构建失败");
            setBuilding(false);
            setBuildStage("");
          }
        } catch { /* 轮询抖动忽略 */ }
      }, 2500);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
      setBuilding(false);
    }
  };

  // 字段级 AI 补写(手工表单"AI 补"按钮,批次二)
  const aiFill = async (field: string) => {
    try {
      setAiBusy(field);
      const r = await api.suggestField(pid, {
        category: draft.category ?? cat, field, name: draft.name ?? "",
        known: (draft.fields ?? {}) as Record<string, string>,
      });
      setDraft({ ...draft, fields: { ...draft.fields, [field]: r.text } });
      flash(`字段已由 AI 填写(¥${r.cost.toFixed(4)}),可再手改`);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    } finally {
      setAiBusy(null);
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
              <span className="row" style={{ margin: 0, gap: 6 }}>
                {f.label}
                <button className="link" style={{ fontSize: 11 }}
                  disabled={aiBusy === f.key}
                  title="AI 按本书信息补写此字段,填入后可手改"
                  onClick={(e) => { e.preventDefault(); aiFill(f.key); }}>
                  {aiBusy === f.key ? "AI 补写中…" : "🤖 AI 补"}
                </button>
              </span>
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
        <div className="row">
          <NamingStudio />
          <button
            className="build-btn"
            onClick={() => setConfirmBuild(true)}
            disabled={building}
            title="仅点击时运行:调用一次模型,整套草案进提案区,人批准才入正式档案"
          >
            {building ? `AI 构建中(${buildStage || "排队"})…` : "AI 一键构建(后台)"}
          </button>
        </div>
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
        · 树形挂靠:条目可「+子」挂出任意深度的设定树(同类嵌套,删大节点连子树)
      </div>

      {(() => {
        // 批次甲:设定树(同类自由嵌套,折叠记忆按书持久)
        const byParent = new Map<string | null, L1Entry[]>();
        for (const e of inCat) {
          const k = e.parent_entry_id ?? null;
          if (!byParent.has(k)) byParent.set(k, []);
          byParent.get(k)!.push(e);
        }
        const toggleFold = (id: string) => setFolded((cur) => {
          const n = new Set(cur);
          if (n.has(id)) n.delete(id); else n.add(id);
          return n;
        });
        const renderEntry = (e: L1Entry, depth: number): ReactElement => {
          const kids = byParent.get(e.id) ?? [];
          const isFolded = folded.has(e.id);
          const formsOpen = editingId === e.id
            || (creating && (draft.parent_entry_id ?? null) === e.id);
          return (
            <li key={e.id} className={e.entry_status === "proposal" ? "entry proposal" : "entry"}
              style={{ marginLeft: depth * 18 }}>
              <div className="entry-head">
                {kids.length > 0 && (
                  <button className="link" title={isFolded ? "展开子级" : "折叠子级"}
                    onClick={() => toggleFold(e.id)}>{isFolded ? "▸" : "▾"}</button>
                )}
                <b>{e.name}</b>
                <span className="row" style={{ margin: 0 }}>
                  {onShowLinks && (
                    <button className="link" onClick={() => onShowLinks("l1_entry", e.id, e.name)}>
                      🔗 关联
                    </button>
                  )}
                  {e.entry_status === "proposal" ? (
                    <span className="badge warn" title={(() => {
                      const dup = entries.find((x) => x.entry_status === "confirmed"
                        && x.category === e.category && x.name === e.name);
                      return dup ? `与正式条目同名!对照:${(dup.fields && Object.values(dup.fields)[0] || "").slice(0, 80)}` : undefined;
                    })()}>
                      AI 提案 · 待批准
                      {entries.some((x) => x.entry_status === "confirmed"
                        && x.category === e.category && x.name === e.name) && " ⚠同名"}
                    </span>
                  ) : (
                    <span className="badge ok">正式</span>
                  )}
                </span>
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
                    <button onClick={() => startCreate(e.id)}
                      title="在它下面挂同类别子条目(可继续往深挂)">
                      + 子条目
                    </button>
                    <button onClick={() => startEdit(e)}>{editingId === e.id ? "收起" : "编辑"}</button>
                    <button onClick={async () => {
                      if (await uiConfirm(`删除「${e.name}」及其全部子条目?`)) {
                        await api.l1Delete(e.id);
                        flash("已删除(含子树)");
                        load();
                      }
                    }}>删除</button>
                  </>
                )}
              </div>
              {kids.length > 0 && isFolded && (
                <p className="muted small" style={{ margin: "0 0 4px", paddingLeft: 12 }}>
                  (已折叠,{kids.length} 个子条目)
                </p>
              )}
              {kids.length > 0 && !isFolded && kids.map((c) => renderEntry(c, depth + 1))}
              {formsOpen && renderForm(false)}
            </li>
          );
        };
        return (
          <ul className="entry-list">
            {(byParent.get(null) ?? []).map((e) => renderEntry(e, 0))}
            {inCat.length === 0 && (
              <li className="muted">本类还没有条目。手工建档,或用右上角"AI 一键构建"。</li>
            )}
          </ul>
        );
      })()}

      <p className="muted small">{STYLE_NOTE}</p>

      {creating && renderForm(true)}

      <div className="row">
        <button onClick={() => startCreate(null)}>{creating ? "收起新建" : "+ 手工建档"}</button>
      </div>

      <h3>L1 档案库对话(批次二)</h3>
      <ChatPanel
        projectId={pid}
        ownerType="l1"
        ownerId={pid}
        defaultSessionName="档案库讨论"
        allowPresets
        allowSkill
        allowRefs
        emptyHint="档案库对话:上下文=六类条目名录+提案区现状。查缺口/想设定/评条目;正式修改请走提案批准或表单。"
      />
    </div>
  );
}
