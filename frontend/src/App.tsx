import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { STAGE_LABELS } from "./stages";
import type { GenTask } from "./types";
import { ConfirmHost } from "./components/uiConfirm";
import OverviewPage from "./pages/Overview";
import SettingsPage from "./pages/Settings";
import ChatTestPage from "./pages/ChatTest";
import LogsPage from "./pages/Logs";
import HelpPage from "./pages/HelpPage";

const TABS = [
  { key: "overview", label: "总览", el: <OverviewPage /> },
  { key: "settings", label: "设置", el: <SettingsPage /> },
  { key: "chat", label: "测试对话", el: <ChatTestPage /> },
  { key: "logs", label: "日志", el: <LogsPage /> },
  { key: "help", label: "帮助", el: <HelpPage /> },
] as const;

export default function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("overview");
  const [genTasks, setGenTasks] = useState<GenTask[]>([]);
  const [chatDone, setChatDone] = useState(false);

  // 全局"生成中"徽标(需求1):任何页签都可见 哪本书/哪一章/第几阶段;后端为唯一事实源
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api.activeGenTasks()
        .then((r) => { if (alive) setGenTasks(r.tasks); })
        .catch(() => { /* 服务未起等场景静默 */ });
    tick();
    const iv = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  // 回复完成全局提示(体感 2026-09-06):App 层监视——切到设置/日志也不丢;
  // 是否"在看对话"由 BookWorkspace 写 window.__chatViewActive(主对话界面不弹)
  const knownChats = useRef<Set<string>>(new Set());
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api.activeGenTasks()
        .then((r) => {
          if (!alive) return;
          const chats = new Set(r.tasks.filter((t) => t.kind === "chat").map((t) => t.id));
          for (const id of knownChats.current) {
            if (!chats.has(id) && !(window as { __chatViewActive?: boolean }).__chatViewActive) {
              setChatDone(true);
            }
          }
          knownChats.current = chats;
        })
        .catch(() => { });
    const iv = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  return (
    <div className="app">
      <header>
        <h1>Soulspring</h1>
        <nav>
          {TABS.map((t) => (
            <button
              key={t.key}
              className={tab === t.key ? "active" : ""}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
          {genTasks.map((t) => (
            <span key={t.id} className="badge info gen-badge" title="后台生成任务进行中,切页签不打断">
              ⟳ {t.project_name}·{t.node_title}·{STAGE_LABELS[t.stage] ?? t.stage}
            </span>
          ))}
        </nav>
      </header>
      <main>{TABS.find((t) => t.key === tab)!.el}</main>
      {chatDone && (
        <button className="done-toast"
          onClick={() => {
            // 批次三续件:直达对话台(挂 __openChatRequest 标记,工作区挂载时消费切 chat 态)
            (window as { __openChatRequest?: boolean }).__openChatRequest = true;
            setTab("overview");
            setChatDone(false);
          }}>
          💬 AI 回复已完成——点击回到对话台查看
        </button>
      )}
      <ConfirmHost />
      <footer>
        <span className="muted">本地单用户 · 人主编 99% · 核心引擎原创自研(Chevoink 生态互通基于商业授权)</span>
      </footer>
    </div>
  );
}
