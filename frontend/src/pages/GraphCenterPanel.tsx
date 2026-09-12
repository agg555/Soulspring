import { useEffect, useState } from "react";
import { api } from "../api";
import type { GraphBoard, TemplatesList } from "../types";
import GraphBoardView from "../components/GraphCanvas";
import GraphOverview from "../components/GraphOverview";
import { uiConfirm } from "../components/uiConfirm";

/**
 * 图谱中心(第四批 B,任务词 2026-09-01):书工作区图谱入口统一为板列表,
 * 每类图谱 = 一块 board(kind 区分),同一引擎渲染与交互(替代第三批每类一页签)。
 * 类型优先级:人物关系(已迁移)/剧情事件 P0;道具/地点/势力 P1;伏笔/力量/自由板 P2。
 * 批次七⑥:模板双层——题材包一键铺板/新建板选套模板(预设与我的分组);
 * 「存为模板」在自由板画布工具条(GraphCanvas)。
 */
const KIND_LABEL: Record<string, string> = {
  character: "人物关系", event: "剧情事件", item: "道具图谱", map: "地点图谱",
  faction: "势力关系", hook: "伏笔流转", power: "力量体系", free: "自由板", worldview: "世界观概念",
  system: "小说内系统",
};

export default function GraphCenterPanel({ pid, onShowLinks }: {
  pid: string;
  onShowLinks?: (etype: string, nid: string, title: string) => void;   // B3 互链
}) {
  const [boards, setBoards] = useState<GraphBoard[] | null>(null);
  const [kinds, setKinds] = useState<string[]>([]);
  const [openBoard, setOpenBoard] = useState<string | null>(null);
  // 批次三⑥:全书总览(聚合全部板;只读+跳单板,数据同源自动同步)
  const [showOverview, setShowOverview] = useState(false);
  const [nf, setNf] = useState({ kind: "free", name: "" });
  const [tpl, setTpl] = useState("");            // "" | u:<模板id> | p:<包key>:<板idx>
  const [tpls, setTpls] = useState<TemplatesList | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 3500); };

  const load = () => {
    api.graphBoards(pid).then((r) => {
      setBoards(r.boards);
      setKinds(r.kinds);
    }).catch((e) => setError(String(e.message || e)));
    api.templatesList().then(setTpls).catch(() => {});
  };
  useEffect(load, [pid]);

  if (showOverview) {
    return (
      <GraphOverview pid={pid} onOpenBoard={(bid) => { setShowOverview(false); setOpenBoard(bid); }}
        onBack={() => setShowOverview(false)} />
    );
  }

  if (openBoard) {
    return (
      <GraphBoardView boardId={openBoard} onShowLinks={onShowLinks}
        onBack={() => { setOpenBoard(null); load(); }} />
    );
  }

  const create = async () => {
    setError("");
    try {
      let boardId = "";
      if (tpl.startsWith("u:")) {
        const t = tpls?.user.find((x) => x.id === tpl.slice(2));
        const r = await api.applyTemplate(tpl.slice(2), pid, nf.name.trim() || t?.name);
        boardId = r.board.id;
        flash(`已按模板「${t?.name ?? nf.name}」建板(节点/清单完整还原)`);
      } else if (tpl.startsWith("p:")) {
        const [key, idx] = tpl.slice(2).split(":");
        const pack = tpls?.presets.find((x) => x.key === key);
        const pb = pack?.boards[Number(idx)];
        const r = await api.applyPackBoard(key, Number(idx), pid, nf.name.trim() || pb?.name);
        boardId = r.board.id;
        flash(`已按预设「${pack?.name}·${pb?.name}」建板`);
      } else {
        if (!nf.name.trim()) return;
        const r = await api.createGraphBoard(pid, { kind: nf.kind, name: nf.name.trim() });
        boardId = r.board.id;
        flash("图谱板已建");
      }
      setNf({ kind: "free", name: "" });
      setTpl("");
      setOpenBoard(boardId);
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  const applyPackAll = async (key: string, name: string, desc: string) => {
    if (!(await uiConfirm(`把题材包「${name}」的全部板铺进本书?${desc}`))) return;
    setError("");
    try {
      const r = await api.applyPack(key, pid);
      flash(`已铺 ${r.boards.length} 块板(含节点组与清单模板)`);
      load();
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
        {!tpl && (
          <select value={nf.kind} onChange={(e) => setNf({ ...nf, kind: e.target.value })}>
            {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>)}
          </select>
        )}
        {tpl && (
          <select value={tpl === "pick" ? "" : tpl}
            onChange={(e) => setTpl(e.target.value || "pick")} title="套用模板建板">
            <option value="">(选模板…)</option>
            {tpls && tpls.user.length > 0 && (
              <optgroup label="我的模板">
                {tpls.user.map((u) => (
                  <option key={u.id} value={`u:${u.id}`}>
                    {u.name}({u.node_count} 节点)
                  </option>
                ))}
              </optgroup>
            )}
            {tpls && tpls.presets.map((p) => (
              <optgroup key={p.key} label={`预设 · ${p.name}题材包`}>
                {p.boards.map((b, i) => (
                  <option key={i} value={`p:${p.key}:${i}`}>
                    {p.name}·{b.name}({b.node_count} 节点)
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
        <input placeholder="板名,如:道具流转草稿" value={nf.name}
          onChange={(e) => setNf({ ...nf, name: e.target.value })}
          onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
        {!tpl && <button className="link" onClick={() => setTpl("pick")}>从模板建板…</button>}
        {tpl && <button className="primary" onClick={create}>按模板建板</button>}
        {!tpl && <button className="primary" onClick={create}>+ 新建图谱板</button>}
        <button onClick={() => setShowOverview(true)}
          disabled={(boards ?? []).length === 0}
          title="聚合全部板成一张超大全书图谱(只读;数据同源,单板调整自动同步)">
          🌐 全书总览</button>
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
                <button className="link" onClick={async () => {
                  if (await uiConfirm(`删除图谱板「${b.name}」及其全部节点连线?`)) {
                    api.deleteGraphBoard(b.id).then(load);
                  }
                }}>删</button>
              </td>
            </tr>
          ))}
          {(boards ?? []).length === 0 && (
            <tr><td colSpan={5} className="muted">
              还没有图谱板。可一键铺题材包,或新建后用「从档案生成」铺节点。
            </td></tr>
          )}
        </tbody>
      </table>

      {/* 批次七⑥:模板双层(题材包一键 + 我的模板管理) */}
      <h3 className="tpl-sec">📦 题材包(一键铺进本书)</h3>
      <div className="tpl-packs">
        {(tpls?.presets ?? []).map((p) => (
          <div key={p.key} className="tpl-pack">
            <b>{p.name}</b>
            <span className="muted small">{p.description}</span>
            <span className="muted small">{p.board_count} 板 · {p.boards.reduce((a, b) => a + b.node_count, 0)} 节点</span>
            <button className="primary" onClick={() => applyPackAll(p.key, p.name, p.description)}>
              一键铺进本书
            </button>
          </div>
        ))}
        {!tpls && <p className="muted small">加载中…</p>}
      </div>
      <h3 className="tpl-sec">🗂 我的模板(自由板画布里「存为模板」生成)</h3>
      {(tpls?.user ?? []).length === 0 && (
        <p className="muted small">还没有自定义模板。打开一块自由板,点工具条「🖻 存为模板」。</p>
      )}
      <ul className="tpl-user-list">
        {(tpls?.user ?? []).map((u) => (
          <li key={u.id}>
            <b>{u.name}</b>
            <span className="muted small">{KIND_LABEL[u.kind] ?? u.kind} · {u.node_count} 节点</span>
            <button className="link" onClick={async () => {
              if (!(await uiConfirm(`删除模板「${u.name}」?(已建好的板不受影响)`))) return;
              api.deleteTemplate(u.id).then(() => { flash("模板已删"); load(); });
            }}>删</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
