import { useEffect, useState } from "react";
import { api } from "../api";
import type { GraphBoard } from "../types";
import GraphBoardView from "../components/GraphCanvas";

/**
 * 图谱中心(第四批 B,任务词 2026-09-01):书工作区图谱入口统一为板列表,
 * 每类图谱 = 一块 board(kind 区分),同一引擎渲染与交互(替代第三批每类一页签)。
 * 类型优先级:人物关系(已迁移)/剧情事件 P0;道具/地点/势力 P1;伏笔/力量/自由板 P2。
 */
const KIND_LABEL: Record<string, string> = {
  character: "人物关系", event: "剧情事件", item: "道具图谱", map: "地点图谱",
  faction: "势力关系", hook: "伏笔流转", power: "力量体系", free: "自由板", worldview: "世界观概念",
};

export default function GraphCenterPanel({ pid }: { pid: string }) {
  const [boards, setBoards] = useState<GraphBoard[] | null>(null);
  const [kinds, setKinds] = useState<string[]>([]);
  const [openBoard, setOpenBoard] = useState<string | null>(null);
  const [nf, setNf] = useState({ kind: "free", name: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 3500); };

  const load = () => {
    api.graphBoards(pid).then((r) => {
      setBoards(r.boards);
      setKinds(r.kinds);
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, [pid]);

  if (openBoard) {
    return <GraphBoardView boardId={openBoard} onBack={() => { setOpenBoard(null); load(); }} />;
  }

  const create = async () => {
    if (!nf.name.trim()) return;
    setError("");
    try {
      const r = await api.createGraphBoard(pid, { kind: nf.kind, name: nf.name.trim() });
      setNf({ kind: "free", name: "" });
      flash("图谱板已建");
      setOpenBoard(r.board.id);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  return (
    <div>
      <p className="muted small">
        统一图谱引擎:方框节点 + 网格吸附 + 拖动连线;人的拖动/连线直接生效,
        AI 改动一律走建议确认(优化/奇思妙想),无直改。
      </p>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="row" style={{ flexWrap: "wrap" }}>
        <select value={nf.kind} onChange={(e) => setNf({ ...nf, kind: e.target.value })}>
          {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>)}
        </select>
        <input placeholder="板名,如:道具流转草稿" value={nf.name}
          onChange={(e) => setNf({ ...nf, name: e.target.value })}
          onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
        <button className="primary" onClick={create}>+ 新建图谱板</button>
      </div>

      <table>
        <thead><tr><th>板</th><th>类型</th><th>节点</th><th>连线</th><th></th></tr></thead>
        <tbody>
          {(boards ?? []).map((b) => (
            <tr key={b.id}>
              <td><button className="link" onClick={() => setOpenBoard(b.id)}><b>{b.name}</b></button></td>
              <td><span className="badge info">{KIND_LABEL[b.kind] ?? b.kind}</span></td>
              <td>{b.node_count ?? 0}</td>
              <td>{b.edge_count ?? 0}</td>
              <td>
                <button className="link" onClick={() => {
                  if (confirm(`删除图谱板「${b.name}」及其全部节点连线?`)) {
                    api.deleteGraphBoard(b.id).then(load);
                  }
                }}>删</button>
              </td>
            </tr>
          ))}
          {(boards ?? []).length === 0 && (
            <tr><td colSpan={5} className="muted">
              还没有图谱板。新建后可用「从档案生成」一键铺节点;人物关系已自动迁移一块板。
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
