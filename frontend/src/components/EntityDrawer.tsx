import { useEffect, useState } from "react";
import { api } from "../api";
import type { EntityLinks } from "../types";

/**
 * B3 实体互链抽屉(骨架批执行书 §3,2026-09-04):点任意实体 → 抽屉聚合展示其
 * 关联对象(图谱边/事件关联/大纲树关系/章节正文引用),点条目跳到它所在版块。
 * 联动枢纽:面板间靠它互跳(onJump 由面板宿主路由),不做面板间硬编码互调。
 */
const ETYPE_LABEL: Record<string, string> = {
  outline_node: "大纲节点", graph_node: "图谱节点",
  timeline_event: "时间线事件", l1_entry: "档案条目",
};

export default function EntityDrawer({ pid, etype, id, title, onClose, onJump }: {
  pid: string;
  etype: string;
  id: string;
  title: string;
  onClose: () => void;
  onJump: (etype: string, nid: string, ntitle: string) => void;
}) {
  const [data, setData] = useState<EntityLinks | null>(null);
  const [error, setError] = useState("");
  const [pinMsg, setPinMsg] = useState("");
  // 批次三④:把该实体钉成自由板的"实体链接卡"(无自由板则自动建一块)
  const pinToFree = async (it: { etype?: string; id: string; title: string }) => {
    if (!it.etype) return;
    try {
      const bs = await api.graphBoards(pid);
      let free = bs.boards.find((b) => b.kind === "free");
      if (!free) free = (await api.createGraphBoard(pid, { kind: "free", name: "自由板" })).board;
      const nn = await api.createGraphNode(free.id, { label: it.title, ref_type: "free" });
      await api.patchGraphNode(nn.node.id, {
        style: { card: "link", ref: { etype: it.etype, id: it.id, title: it.title } },
      });
      setPinMsg(`已钉到「${free.name}」:${it.title}`);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  };
  useEffect(() => {
    setData(null); setError("");
    api.entityLinks(pid, etype, id)
      .then(setData)
      .catch((e) => setError(String(e.message || e)));
  }, [pid, etype, id]);

  return (
    <>
      {/* 体感三桶第三轮:点抽屉外即关闭,杜绝点击/长按穿透抽屉底下画布的冲突 */}
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="dialog entity-drawer">
      <div className="row spread">
        <b>🔗 关联 · {title}</b>
        <button className="link" onClick={onClose}>关闭</button>
      </div>
      <p className="muted small">{ETYPE_LABEL[etype] ?? etype}的关联对象;点条目跳到它所在的版块。📌=钉到自由板(实体链接卡)。</p>
      {pinMsg && <p className="ok">{pinMsg}</p>}
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted small">加载中…</p>}
      {data && data.groups.length === 0 && <p className="muted small">暂无关联对象。</p>}
      {data && data.groups.map((g) => (
        <div key={g.kind}>
          <h3>{g.kind}({g.items.length})</h3>
          <ul className="entity-link-list">
            {g.items.map((it) => (
              <li key={it.id}>
                <button className="link" title="跳转到该对象"
                  onClick={() => it.etype && onJump(it.etype, it.id, it.title)}>
                  {it.title}
                </button>
                {it.extra && <span className="muted small"> · {it.extra}</span>}
                {it.etype && (
                  <button className="link" title="钉到自由板(实体链接卡,批次三④)"
                    onClick={() => pinToFree(it)}>📌 钉</button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      </div>
    </>
  );
}
