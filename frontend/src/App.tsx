import { useEffect, useState } from "react";
import { api } from "./api";
import { STAGE_LABELS } from "./stages";
import type { GenTask } from "./types";
import OverviewPage from "./pages/Overview";
import SettingsPage from "./pages/Settings";
import ChatTestPage from "./pages/ChatTest";
import LogsPage from "./pages/Logs";

const TABS = [
  { key: "overview", label: "总览", el: <OverviewPage /> },
  { key: "settings", label: "设置", el: <SettingsPage /> },
  { key: "chat", label: "测试对话", el: <ChatTestPage /> },
  { key: "logs", label: "日志", el: <LogsPage /> },
] as const;

export default function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("overview");
  const [genTasks, setGenTasks] = useState<GenTask[]>([]);

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
      <footer>
        <span className="muted">本地单用户 · 人主编 99% · M1 薄核</span>
      </footer>
    </div>
  );
}
