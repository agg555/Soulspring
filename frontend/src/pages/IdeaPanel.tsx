import { useEffect, useState, type ReactElement } from "react";
import { api } from "../api";
import type { IdeaNode } from "../types";
import ChatPanel from "../components/ChatPanel";
import { uiConfirm, uiPrompt } from "../components/uiConfirm";

/**
 * 构思树(批次七⑤,执行书附节六节方案用户审通过):
 * - 左栏第 4 页签;树形缩进列表(根=1,深度≤3),每行=标题+状态徽标+行内动作;
 * - 下钻入口:对话台建议卡「💭下钻」(CustomEvent 直达本面板开子线)与行内「+子构思」;
 * - 三态收敛:待议→采纳(标记共识;写回仍走建议采纳闸门)/放弃(冻结不喂 AI)/回待议;
 * - 子讨论=对话框内 ChatPanel(owner idea),空态=引导卡零预填。
 */
const STATUS_BADGE: Record<IdeaNode["status"], string> = {
  open: "待议", adopted: "已采纳", dropped: "已放弃",
};

export default function IdeaPanel({ pid, drillTarget, onConsumedDrill }: {
  pid: string;
  drillTarget?: string | null;      // 对话台「💭下钻」直达的构思 id
  onConsumedDrill?: () => void;
}) {
  const [ideas, setIdeas] = useState<IdeaNode[] | null>(null);
  const [openIdea, setOpenIdea] = useState<IdeaNode | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 3500); };

  const load = () =>
    api.ideasList(pid).then((r) => setIdeas(r.ideas))
      .catch((e) => setError(String((e as Error).message || e)));
  useEffect(() => { load(); }, [pid]);

  useEffect(() => {
    if (!drillTarget) return;
    onConsumedDrill?.();
    api.ideasList(pid).then((r) => {
      setIdeas(r.ideas);
      const it = r.ideas.find((x) => x.id === drillTarget);
      if (it) setOpenIdea(it);
    }).catch(() => {});
  }, [drillTarget, pid, onConsumedDrill]);

  const byParent = new Map<string | null, IdeaNode[]>();
  for (const i of ideas ?? []) {
    const k = i.parent_idea_id ?? null;
    if (!byParent.has(k)) byParent.set(k, []);
    byParent.get(k)!.push(i);
  }

  const addRoot = async () => {
    const title = await uiPrompt("记个奇思妙想(标题)");
    if (!title || !title.trim()) return;
    try {
      await api.ideasCreate({ pid, title: title.trim() });
      flash("已记下,点「💬 子讨论」开聊");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const addChild = async (parent: IdeaNode) => {
    const title = await uiPrompt(`「${parent.title}」下的子构思标题`);
    if (!title || !title.trim()) return;
    try {
      await api.ideasCreate({ pid, title: title.trim(), parent_idea_id: parent.id });
      flash("子构思已挂上(深度≤3)");
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));   // 深度超限/父冻结在此可读报错
    }
  };

  const setStatus = async (i: IdeaNode, status: IdeaNode["status"]) => {
    try {
      await api.ideasPatch(i.id, { status });
      flash(status === "adopted" ? "已标记采纳(共识达成;字段写回仍走建议采纳闸门)"
        : status === "dropped" ? "已放弃(冻结,不再喂 AI;可回待议)" : "已回待议");
      load();
      setOpenIdea((cur) => (cur && cur.id === i.id ? { ...cur, status } : cur));
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const remove = async (i: IdeaNode) => {
    if (!(await uiConfirm(`删除构思「${i.title}」及其全部子构思?`))) return;
    try {
      const r = await api.ideasDelete(i.id);
      flash(`已删 ${r.deleted} 条`);
      setOpenIdea((cur) => (cur && cur.id === i.id ? null : cur));
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const row = (i: IdeaNode): ReactElement => (
    <div key={i.id}>
      <div className={`idea-row idea-dropped-${i.status === "dropped"}`}
        style={{ marginLeft: (i.depth - 1) * 16 }}>
        <button className="link idea-title" title="打开子讨论"
          onClick={() => setOpenIdea(i)}>
          {i.depth > 1 && <span className="muted">└ </span>}{i.title}
        </button>
        <span className={`badge ${i.status === "adopted" ? "ok" : i.status === "dropped" ? "" : "info"}`}>
          {STATUS_BADGE[i.status]}
        </span>
        <span className="idea-actions">
          {i.depth < 3 && i.status !== "dropped" && (
            <button className="link" title="挂一条子构思" onClick={() => addChild(i)}>+子构思</button>
          )}
          {i.status === "open" && (
            <>
              <button className="link" onClick={() => setStatus(i, "adopted")}>采纳</button>
              <button className="link" onClick={() => setStatus(i, "dropped")}>放弃</button>
            </>
          )}
          {i.status !== "open" && (
            <button className="link" onClick={() => setStatus(i, "open")}>回待议</button>
          )}
          <button className="link" onClick={() => remove(i)}>删</button>
        </span>
      </div>
      {(byParent.get(i.id) ?? []).map(row)}
    </div>
  );

  return (
    <div>
      <div className="row">
        <button className="primary" onClick={addRoot}>+ 记个奇思妙想</button>
        <span className="muted small">深度≤3;采纳/放弃=收敛标记,写回永远走建议采纳闸门</span>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      {ideas !== null && ideas.length === 0 && (
        <div className="empty-hint">
          还没有构思。两个入口:①对话台建议卡点「💭下钻」,建议自动变成一条构思;<br />
          ②这里点「+ 记个奇思妙想」手动起一条。三态流转:待议 → 采纳(写回走闸门)/ 放弃(冻结)。
        </div>
      )}
      <div className="idea-tree">
        {(byParent.get(null) ?? []).map(row)}
      </div>

      {openIdea && (
        <>
          <div className="drawer-backdrop" onClick={() => setOpenIdea(null)} />
          <div className="dialog idea-dialog">
            <div className="row spread" style={{ margin: 0 }}>
              <b>💭 {openIdea.title}</b>
              <span className="row" style={{ margin: 0 }}>
                {openIdea.status === "open" && (
                  <>
                    <button className="link" onClick={() => setStatus(openIdea, "adopted")}>采纳转正</button>
                    <button className="link" onClick={() => setStatus(openIdea, "dropped")}>放弃冻结</button>
                  </>
                )}
                {openIdea.status !== "open" && (
                  <button className="link" onClick={() => setStatus(openIdea, "open")}>回待议</button>
                )}
                <button className="link" onClick={() => setOpenIdea(null)}>关闭</button>
              </span>
            </div>
            {openIdea.note && <p className="muted small">{openIdea.note}</p>}
            <p className="muted small">
              子讨论上下文=父链层叠摘要(每层构思+前情提要);放弃后本线冻结不喂 AI。
            </p>
            <div className="idea-chat-wrap">
              <ChatPanel
                projectId={pid}
                ownerType="idea"
                ownerId={openIdea.id}
                defaultSessionName={openIdea.title.slice(0, 20)}
                emptyHint="围绕这条构思开聊;有具体改法时 AI 会给建议块(采纳走闸门)。"
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
