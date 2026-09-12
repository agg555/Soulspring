import { useState } from "react";
import type { SubtopicItem } from "../types";

/**
 * 子题树编辑器(WPS 大纲 AI 闸门,任务词 2026-09-09 阶段 3):
 * AI 出的子题树先弹这里,人可增删改(改标题/删项/加根级/加子级)再批准落库;
 * NodeDrawer(AI 拆子题)与 ChatPanel(subtopic_add 建议)共用一道闸门交互。
 * 纯前端编辑不落库;"加同级"= 父行「+子」或根级「+」,批准时空标题项自动剔除。
 */

let _uid = 0;
const nextKey = () => `st_${Date.now().toString(36)}_${++_uid}`;

type Row = { _key: string; title: string; children: Row[] };

const withKeys = (items: SubtopicItem[]): Row[] =>
  items.map((it) => ({
    _key: nextKey(),
    title: it.title ?? "",
    children: withKeys(it.children ?? []),
  }));

const stripRows = (rows: Row[]): SubtopicItem[] =>
  rows.filter((r) => r.title.trim())
    .map((r) => ({ title: r.title.trim(), children: stripRows(r.children) }));

export default function SubtopicTreeEditor({ tree, onChange, maxDepth = 8 }: {
  tree: SubtopicItem[];
  onChange: (next: SubtopicItem[]) => void;
  maxDepth?: number;
}) {
  const [rows, setRows] = useState<Row[]>(() => withKeys(tree));
  const commit = (next: Row[]) => { setRows(next); onChange(stripRows(next)); };

  const patch = (key: string, fn: (r: Row) => Row, list: Row[] = rows): Row[] =>
    list.map((r) => (r._key === key ? fn(r) : { ...r, children: patch(key, fn, r.children) }));

  const remove = (key: string): void => {
    const cut = (list: Row[]): Row[] =>
      list.filter((r) => r._key !== key).map((r) => ({ ...r, children: cut(r.children) }));
    commit(cut(rows));
  };

  const renderRows = (list: Row[], depth: number): React.ReactNode =>
    list.map((r) => (
      <div key={r._key}>
        <div className="row" style={{ margin: "3px 0", marginLeft: depth * 18 }}>
          <input
            value={r.title}
            placeholder={`子题标题(第 ${depth + 1} 层)`}
            onChange={(e) => commit(patch(r._key, (x) => ({ ...x, title: e.target.value })))}
            style={{ flex: 1 }}
          />
          {depth + 1 < maxDepth && (
            <button className="link" title="在该子题下加子级"
              onClick={() => commit(patch(r._key, (x) => ({
                ...x, children: [...x.children, { _key: nextKey(), title: "", children: [] }],
              })))}>
              +子
            </button>
          )}
          <button className="link danger-link" title="删除该项(子级一并删)"
            onClick={() => remove(r._key)}>删</button>
        </div>
        {r.children.length > 0 && renderRows(r.children, depth + 1)}
      </div>
    ));

  return (
    <div className="subtopic-editor">
      {rows.length === 0 && <p className="muted small">(空树——先加子题再批准)</p>}
      {renderRows(rows, 0)}
      <div className="row" style={{ marginTop: 6 }}>
        <button className="link"
          onClick={() => commit([...rows, { _key: nextKey(), title: "", children: [] }])}>
          + 根级子题
        </button>
      </div>
    </div>
  );
}
