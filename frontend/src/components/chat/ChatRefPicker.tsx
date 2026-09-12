import type { AttachmentRef, ChatRefs } from "../../types";

/** @引用选择器(大文件拆分批 2026-09-10 自 ChatPanel.tsx 抽出;纯移动零行为变化):
 * 章/角色条目/伏笔三页签,点「引用」变附件 chip 随下一条消息附加。
 * refs 已由父组件判空(pickerOpen && refs),本件按非空接。 */
export default function ChatRefPicker({
  refs, pickerTab, setPickerTab, setPickerOpen, addChip,
}: {
  refs: ChatRefs;
  pickerTab: "chapter" | "entry" | "hook";
  setPickerTab: (t: "chapter" | "entry" | "hook") => void;
  setPickerOpen: (v: boolean) => void;
  addChip: (ref: AttachmentRef) => void;
}) {
  return (
    <div className="dialog ref-picker">
      <div className="row">
        {(["chapter", "entry", "hook"] as const).map((t) => (
          <button key={t} className={pickerTab === t ? "active" : ""}
            onClick={() => setPickerTab(t)}>
            {t === "chapter" ? "章" : t === "entry" ? "角色/条目" : "伏笔"}
          </button>
        ))}
        <span className="spread" />
        <button className="link" onClick={() => setPickerOpen(false)}>收起</button>
      </div>
      <ul className="entry-list">
        {pickerTab === "chapter" && refs.chapters.map((c) => (
          <li key={c.id} className="entry entry-head">
            <b>{c.title}</b>
            <span className="badge">{c.status}</span>
            <button className="link" onClick={() => addChip({ type: "chapter", id: c.id, label: c.title })}>引用</button>
          </li>
        ))}
        {pickerTab === "entry" && refs.entries.map((e) => (
          <li key={e.id} className="entry entry-head">
            <span className="badge">{e.category}</span>
            <b>{e.name}</b>
            <button className="link" onClick={() => addChip({ type: "entry", id: e.id, label: e.name })}>引用</button>
          </li>
        ))}
        {pickerTab === "hook" && refs.hooks.length === 0 && <li className="muted small">伏笔池为空。</li>}
        {pickerTab === "hook" && refs.hooks.map((h, i) => (
          <li key={i} className="entry entry-head">
            <span className="badge">{h.status}</span>
            <span className="small">{h.detail.slice(0, 60)}{h.detail.length > 60 ? "…" : ""}</span>
            <button className="link"
              onClick={() => addChip({ type: "hook", label: h.detail.slice(0, 120) })}>引用</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
