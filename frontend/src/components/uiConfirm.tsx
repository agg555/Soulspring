/**
 * 行内确认/输入条(uiConfirm/uiPrompt)——替代原生 confirm()/prompt()。
 *
 * 背景(实跑 2026-09-02):ZCode 内嵌浏览器面板无法处理原生模态对话框——
 * prompt 被静默吞掉(改标签永远取消),confirm 直接挂死整个页签的命令通道
 * (回滚按钮实测)。本组件提供非模态确认条:模块级 Promise 总线 + 根部宿主渲染,
 * 调用方 `if (await uiConfirm("…"))` 与原生用法几乎同形,替换成本最小。
 * 样式从简(吸顶一条),只求内嵌面板可用;后续可再美化。
 */
import { useEffect, useRef, useState } from "react";

type Pending =
  | { kind: "confirm"; message: string; resolve: (v: boolean) => void }
  | { kind: "prompt"; message: string; defaultValue: string; resolve: (v: string | null) => void };

let listener: ((p: Pending) => void) | null = null;

export function uiConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    const p: Pending = { kind: "confirm", message, resolve };
    if (listener) listener(p);
    else resolve(window.confirm(message)); // 宿主未挂载(测试环境)时退回原生
  });
}

export function uiPrompt(message: string, defaultValue = ""): Promise<string | null> {
  return new Promise((resolve) => {
    const p: Pending = { kind: "prompt", message, defaultValue, resolve };
    if (listener) listener(p);
    else resolve(window.prompt(message, defaultValue));
  });
}

export function ConfirmHost() {
  const [pending, setPending] = useState<Pending | null>(null);
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listener = (p) => {
      setPending(p);
      setText(p.kind === "prompt" ? p.defaultValue : "");
      // 下一个帧聚焦输入框,键盘流不中断
      setTimeout(() => inputRef.current?.focus(), 30);
    };
    return () => { listener = null; };
  }, []);

  if (!pending) return null;

  const done = (value: boolean) => {
    if (pending.kind === "confirm") pending.resolve(value);
    else pending.resolve(value ? text : null); // prompt:确认返回输入文本,取消返回 null
    setPending(null);
  };

  return (
    <div className="confirm-bar" role="alertdialog" aria-label={pending.message}>
      <span>{pending.message}</span>
      {pending.kind === "prompt" && (
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") done(true);
            if (e.key === "Escape") done(false);
          }}
          style={{ flex: "1 1 160px" }}
        />
      )}
      <button className="primary" onClick={() => done(true)}>确定</button>
      <button onClick={() => done(false)}>取消</button>
    </div>
  );
}
