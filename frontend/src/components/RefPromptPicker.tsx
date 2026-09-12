import { useState } from "react";
import type { RefPromptItem } from "../types";

/**
 * 参考提示词选择器(2026-09-09 拍板:长文本生成入口可挂参考提示词,多选+搜索)。
 * 选中=运行时手选(优先于设置台的三层绑定);不点开=走绑定链。
 * 宿主:工作台草稿/自修、节点抽屉正文建议/子题拆分。
 */
export default function RefPromptPicker({ items, selected, onChange }: {
  items: RefPromptItem[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const shown = items.filter((i) =>
    !q.trim() || i.name.includes(q.trim()) || i.text.includes(q.trim()));
  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  if (items.length === 0) return null;
  return (
    <span className="refprompt-picker" style={{ position: "relative", display: "inline-block" }}>
      <button className="link" title="参考提示词:选中的条目随本次生成注入(仅作参考)"
        onClick={() => setOpen(!open)}>
        💡 提示词{selected.length > 0 ? `·已选${selected.length}` : ""}
      </button>
      {open && (
        <div className="dialog" style={{ position: "absolute", zIndex: 30, minWidth: 300 }}>
          <div className="row">
            <input autoFocus placeholder="搜索提示词…" value={q}
              onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
            <button className="link" onClick={() => setOpen(false)}>收起</button>
          </div>
          {shown.length === 0 && <p className="muted small">(没有匹配的提示词;设置台可新建)</p>}
          <ul className="entry-list" style={{ maxHeight: 240, overflow: "auto" }}>
            {shown.map((i) => (
              <li key={i.id} className="entry entry-head" style={{ cursor: "pointer" }}
                onClick={() => toggle(i.id)}>
                <input type="checkbox" checked={selected.includes(i.id)} readOnly
                  onClick={(e) => { e.stopPropagation(); toggle(i.id); }} />
                <b>{i.name}</b>
                <span className="muted small" style={{ flex: 1 }}>
                  {i.text.slice(0, 40)}{i.text.length > 40 ? "…" : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </span>
  );
}
