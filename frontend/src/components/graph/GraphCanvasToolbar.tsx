/**
 * 图谱板级工具条(大文件拆分批 2026-09-10 自 GraphCanvas.tsx 抽出;纯移动零行为变化):
 * 自由节点名输入 + 卡型选择 + 内置模板 + 从档案生成。按板型(kind)显示不同动作,
 * 落库逻辑全在 GraphCanvas,本件只负责渲染与回调转发。
 */
import type { GraphBoard } from "../../types";

export default function GraphCanvasToolbar({
  board, nodeLabel, onNodeLabelChange, onAddFreeNode,
  newCard, onNewCardChange, onAddTemplate, onSaveAsTemplate,
  genCat, onGenCatChange, onGenerate,
}: {
  board: GraphBoard | null;
  nodeLabel: string;
  onNodeLabelChange: (v: string) => void;
  onAddFreeNode: () => void;
  newCard: "text" | "checklist";
  onNewCardChange: (v: "text" | "checklist") => void;
  onAddTemplate: (title: string, items: string[]) => void;
  onSaveAsTemplate: () => void;
  genCat: string;
  onGenCatChange: (v: string) => void;
  onGenerate: (source: string, category?: string) => void;
}) {
  return (
    <div className="row" style={{ flexWrap: "wrap" }}>
      <input placeholder="自由节点名" value={nodeLabel}
        onChange={(e) => onNodeLabelChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") onAddFreeNode(); }} />
      {board?.kind === "free" && (
        <select value={newCard} title="自由节点卡型(批次三④)"
          onChange={(e) => onNewCardChange(e.target.value as "text" | "checklist")}>
          <option value="text">文本卡</option>
          <option value="checklist">清单卡</option>
        </select>
      )}
      <button onClick={onAddFreeNode} disabled={!nodeLabel.trim()}>+ 自由节点</button>
      {board?.kind === "free" && (
        <>
          <button title="内置模板:章检查单(清单卡)"
            onClick={() => onAddTemplate("章检查单", [
              "主线推进了吗", "伏笔埋/收对齐", "时间线不冲突",
              "人物言行一致", "字数达标", "开头/结尾钩子",
            ])}>📋 章检查单</button>
          <button title="内置模板:卷待办(清单卡)"
            onClick={() => onAddTemplate("卷待办", [
              "待补设定:", "待写章节:", "待回收伏笔:",
            ])}>📝 卷待办</button>
          {/* 批次七⑥:整板存为我的模板(存→选→套闭环的「存」端) */}
          <button title="把整板存为我的模板(节点/清单/连线完整还原,新建板时可套用)"
            onClick={onSaveAsTemplate}>存为模板</button>
        </>
      )}
      {board?.kind === "item" || board?.kind === "map" || board?.kind === "faction"
        || board?.kind === "character" || board?.kind === "power" || board?.kind === "worldview" ? (
        <>
          <select value={genCat} onChange={(e) => onGenCatChange(e.target.value)}>
            <option value="">从档案生成(L1 类别)…</option>
            {(board.kind === "item" ? [["item_economy", "物品经济"]] :
              board.kind === "map" ? [["map", "地图"]] :
              board.kind === "faction" ? [["faction", "势力阵营"]] :
              board.kind === "character" ? [["character", "角色"]] :
              board.kind === "power" ? [["power", "力量体系"]] :
              [["worldview", "世界观"]]).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
          <button onClick={() => onGenerate("l1_entry", genCat)} disabled={!genCat}>生成节点</button>
        </>
      ) : board?.kind === "event" ? (
        <button onClick={() => onGenerate("timeline_event")}>从时间线生成事件节点</button>
      ) : null}
      <span className="muted small">
        空白拖动=平移 · 滚轮=缩放 · 拖节点落格,靠近锚点松手自动连线 · 点连线中点弹菜单
      </span>
    </div>
  );
}
