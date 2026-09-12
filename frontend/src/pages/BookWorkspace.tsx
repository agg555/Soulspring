import { useEffect, useState } from "react";
import { api } from "../api";
import type { Book, SkillInfo } from "../types";
import L1Panel from "./L1Panel";
import OutlinePanel from "./OutlinePanel";
import WorkbenchPanel from "./WorkbenchPanel";
import ReviewPanel from "./ReviewPanel";
import L2BoardPanel from "./L2BoardPanel";
import ChaishuPanel from "./ChaishuPanel";
import DashboardPanel from "./DashboardPanel";
import TimelinePanel from "./TimelinePanel";
import ReviewCardPanel from "../components/ReviewCardPanel";
import ReadingMode from "../components/ReadingMode";
import GraphCenterPanel from "./GraphCenterPanel";
import OutlineCanvasPanel from "./OutlineCanvasPanel";
import ChatPanel from "../components/ChatPanel";
import EntityDrawer from "../components/EntityDrawer";
import SearchBox from "../components/SearchBox";
import IdeaPanel from "./IdeaPanel";

/**
 * 书工作区三栏骨架(骨架批批次一,执行书 2026-09-02 v1.2 §1/§4,2026-09-04 实施):
 * - 左·功能区:大纲树(默认)/L1 档案库/书籍信息,可切换;
 * - 中·agent 对话台(常态,书级多线+起步方向卡+建议走采纳闸门)↔ 任务台(写章
 *   工作台/终审对话台,重交互占中央)双模式;
 * - 右·功能区:图谱中心(默认)/书况台/剧情时间线/L2 看板/拆书官,可切换;
 * - 左右栏可折叠;原 10 页签功能全部在新壳可达(批次一判据:功能不丢)。
 * 版块化红线:各版块 = 可插拔面板,由本壳(面板宿主)组织,不硬编码互调;
 * B3 互链抽屉落地后作为跨版块跳转枢纽(执行书 §3)。
 */
const LEFT_PANELS = [
  { key: "outline", label: "大纲树" },
  { key: "l1", label: "档案库" },
  { key: "info", label: "书籍信息" },
  { key: "ideas", label: "构思" },
] as const;
const RIGHT_PANELS = [
  { key: "graphs", label: "图谱中心" },
  { key: "outcanvas", label: "大纲画布" },
  { key: "dashboard", label: "书况台" },
  { key: "timeline", label: "剧情时间线" },
  { key: "reviewcard", label: "复习卡" },
  { key: "l2board", label: "L2 看板" },
  { key: "chaishu", label: "拆书官" },
] as const;
// 右栏常用 3 个直出,其余收进"更多▾"(大工程②收界面;功能不减)
const RIGHT_PRIMARY: string[] = ["graphs", "dashboard", "timeline"];
const TASK_PANELS = [
  { key: "workbench", label: "写章工作台" },
  { key: "review", label: "终审对话台" },
] as const;
// 拍板 A=a(2026-09-05):宽版块不进窄右栏,右栏放入口卡片,点击弹大窗
const WIDE_PANELS = [
  { key: "dashboard", label: "书况台", icon: "📊", desc: "每章一行 · 质量分 / 成本 / 审计" },
  { key: "l2board", label: "L2 看板", icon: "🗂️", desc: "真相文件 · 草案批准与回写" },
  { key: "chaishu", label: "拆书官", icon: "🔨", desc: "整本拆解 · 断点续跑 · 导入档案" },
] as const;

const FOLLOW_GLOBAL = "__follow_global__";   // 下拉哨兵值:移除单本书覆盖,回到全局默认

// 书级起步方向卡(执行书 §2 拍板:帮铺大纲/帮灌设定/帮写第一章;预设正文在后端 PRESET_PROMPTS)
const BOOK_PRESETS = [
  { key: "book_outline", label: "帮铺大纲", hint: "给出/补全整体大纲结构:卷·近纲·章层级 + 一句话摘要" },
  { key: "book_setting", label: "帮灌设定", hint: "找设定空洞,给 3-5 条可落地的设定补全点子" },
  { key: "book_first", label: "帮写第一章", hint: "第一章起步方案:开场/人物/冲突/钩子 + 2-3 个开篇方向" },
];

export default function BookWorkspace({
  pid,
  onBack,
}: {
  pid: string;
  onBack: () => void;
}) {
  const [book, setBook] = useState<Book | null>(null);
  const [counts, setCounts] = useState<Record<string, Record<string, number>>>({});
  const [centerMode, setCenterMode] = useState<"chat" | "task">("chat");
  const [taskPanel, setTaskPanel] = useState<"workbench" | "review">("workbench");
  const [leftPanel, setLeftPanel] = useState<(typeof LEFT_PANELS)[number]["key"]>("outline");
  const [rightPanel, setRightPanel] = useState<(typeof RIGHT_PANELS)[number]["key"]>("graphs");
  // 右栏"更多▾"下拉开合(大工程②收界面)
  const [moreOpen, setMoreOpen] = useState(false);
  // 阅读模式(候选清单落地批 B):全屏覆盖层
  const [readingMode, setReadingMode] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  // 批次三③体感:某栏"展开全屏"(小面板被抽屉遮挡的根治;Alt+1/2=沉浸收栏)
  // 二期②写作区 B:expanded 增 "center"=写作模式(中栏占满内容区,左右栏隐藏)
  const [expanded, setExpanded] = useState<null | "left" | "center" | "right">(null);
  // 体感三桶第三轮:左右栏可拖拽调宽(localStorage 持久化;上限随视口,可拉到大半屏)
  const [leftW, setLeftW] = useState(300);
  const [rightW, setRightW] = useState(380);
  useEffect(() => {
    try {
      setLeftW(Number(localStorage.getItem("book3:leftW")) || 300);
      setRightW(Number(localStorage.getItem("book3:rightW")) || 380);
    } catch { /* 忽略 */ }
  }, []);
  const startDrag = (side: "l" | "r") => (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = side === "l" ? leftW : rightW;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - startX;
      if (side === "l") {
        const w = Math.min(Math.round(window.innerWidth * 0.6), Math.max(200, startW + dx));
        setLeftW(w);
        try { localStorage.setItem("book3:leftW", String(w)); } catch { /* 存储不可用忽略,宽度本会话仍生效 */ }
      } else {
        const w = Math.min(Math.round(window.innerWidth * 0.7), Math.max(240, startW - dx));
        setRightW(w);
        try { localStorage.setItem("book3:rightW", String(w)); } catch { /* 同上 */ }
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const colDefs = expanded
    ? "minmax(0, 1fr)"   // 全屏态:展开栏独占内容区(中栏隐藏,另侧收起)
    : [
        ...(leftOpen ? [`${leftW}px`, "6px"] : []),
        "minmax(0, 1fr)",
        ...(rightOpen ? ["6px", `${rightW}px`] : []),
      ].join(" ");
  // 批次三③:沉浸模式 Alt+1/Alt+2 隐显左右栏(会话态不入库)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (e.key === "1") { e.preventDefault(); setLeftOpen((v) => !v); }
      if (e.key === "2") { e.preventDefault(); setRightOpen((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const [linksTarget, setLinksTarget] = useState<{ etype: string; id: string; title: string } | null>(null);
  const [widePanel, setWidePanel] = useState<(typeof WIDE_PANELS)[number]["key"] | null>(null);
  const [chatPreset, setChatPreset] = useState<string | null>(null);
  const [chatNonce, setChatNonce] = useState(0);
  const [taskTarget, setTaskTarget] = useState<string | null>(null);
  const [pendingNode, setPendingNode] = useState<string | null>(null);   // 建议块直达抽屉
  // 批次七⑤:对话台「💭下钻」直达构思子线(CustomEvent 由 ChatPanel 发出)
  const [ideaTarget, setIdeaTarget] = useState<string | null>(null);
  useEffect(() => {
    const h = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      setLeftPanel("ideas");
      setLeftOpen(true);
      setIdeaTarget(id);
    };
    window.addEventListener("soulspring:idea-drill", h);
    return () => window.removeEventListener("soulspring:idea-drill", h);
  }, []);
  // 体感 2026-09-06:回复完成提示由 App 层全局监视;这里只声明"当前是否在看对话"
  // 批次三续件:完成弹条"回到对话台"——挂载/更新时消费 App 层请求标记切 chat 态
  useEffect(() => {
    const w = window as { __openChatRequest?: boolean };
    if (w.__openChatRequest) {
      w.__openChatRequest = false;
      setCenterMode("chat");
    }
  }, []);
  useEffect(() => {
    (window as { __chatViewActive?: boolean }).__chatViewActive =
      centerMode === "chat";
    return () => {
      (window as { __chatViewActive?: boolean }).__chatViewActive = false;
    };
  }, [centerMode]);
  const openSugNode = (nid: string) => {
    setPendingNode(nid); setLeftPanel("outline"); setLeftOpen(true);
  };
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillCfg, setSkillCfg] = useState<{ override: string | null; global: string; effective: string } | null>(null);

  const load = () => {
    api.book(pid).then((r) => {
      setBook(r.book);
      setCounts(r.l1_counts);
      setSkillCfg({
        override: (r as { skill_override?: string | null }).skill_override ?? null,
        global: (r as { skill_global?: string }).skill_global ?? "",
        effective: (r as { skill_effective?: string }).skill_effective ?? "",
      });
    }).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, [pid]);

  useEffect(() => {
    api.reviewSkills().then((r) => setSkills(r.skills)).catch(() => setSkills([]));
  }, []);
  // 体感 2026-09-06:书籍信息页加"可点但不密集"的快捷入口+一行统计
  const [outlineStats, setOutlineStats] = useState<{ ch: number; fin: number; vol: number } | null>(null);
  useEffect(() => {
    api.outline(pid).then((r) => {
      const ns = r.nodes as { kind: string; status: string }[];
      setOutlineStats({
        ch: ns.filter((n) => n.kind === "chapter").length,
        fin: ns.filter((n) => n.kind === "chapter" && n.status === "finalized").length,
        vol: ns.filter((n) => n.kind === "volume").length,
      });
    }).catch(() => setOutlineStats(null));
  }, [pid]);

  const skillName = (key: string) => skills.find((x) => x.key === key)?.name ?? key;

  const setBookSkill = async (value: string) => {
    setError("");
    try {
      await api.setBookSkill(pid, value === FOLLOW_GLOBAL ? null : value);
      setMsg("单本书技能已保存,下次生成本书时生效");
      setTimeout(() => setMsg(""), 3000);
      load();
    } catch (e: unknown) {
      setError(String((e as Error).message || e));
    }
  };

  if (error && !book) return <div><button onClick={onBack}>← 返回书架</button><p className="error">{error}</p></div>;
  if (!book) return <p className="muted">加载中…</p>;

  const confirmed = (cat: string) => counts[cat]?.confirmed ?? 0;
  const proposals = (cat: string) => counts[cat]?.proposal ?? 0;

  // 大纲树里"去工作台/终审台"的跳转 → 中央切任务台(面板宿主路由,不硬编码互调)
  const goTask = (t: "workbench" | "review", nodeId?: string) => {
    if (nodeId) setTaskTarget(nodeId);
    setTaskPanel(t); setCenterMode("task"); setWidePanel(null);
  };
  // 批次二:大纲树"AI 体检"等 → 中央视台直选预设
  const askAI = (preset: string) => {
    setChatPreset(preset); setChatNonce((n) => n + 1); setCenterMode("chat");
  };

  // B3 互链枢纽(执行书 §3):各版块 🔗 按钮 → 抽屉;抽屉内点条目 → 宿主路由到所在版块
  const showLinks = (etype: string, id: string, title: string) => setLinksTarget({ etype, id, title });
  const jumpEntity = (etype: string, id: string, title: string) => {
    if (etype === "outline_node" || etype === "l1_entry") {
      setLeftPanel(etype === "outline_node" ? "outline" : "l1");
      setLeftOpen(true);
    } else {
      setRightPanel(etype === "timeline_event" ? "timeline" : "graphs");
      setRightOpen(true);
    }
    setLinksTarget({ etype, id, title });
  };

  return (
    <div className="book3-wrap">
      <div className="book3-head">
        <button onClick={onBack}>← 书架</button>
        <b>{book.name}</b>
        <span className="muted small">
          {[book.genre, book.audience, ...(book.tropes ?? [])].filter(Boolean).join(" · ")}
        </span>
        <span className="row" style={{ margin: 0 }}>
          <button className={centerMode === "chat" ? "active" : ""}
            onClick={() => setCenterMode("chat")}>💬 对话台</button>
          <button className={centerMode === "task" ? "active" : ""}
            onClick={() => setCenterMode("task")}>⚒ 任务台</button>
          {centerMode === "task" && TASK_PANELS.map((t) => (
            <button key={t.key} className={`link ${taskPanel === t.key ? "" : "muted"}`}
              onClick={() => setTaskPanel(t.key)}>{t.label}</button>
          ))}
        </span>
        {/* 批次七②:全局搜索(FTS5 分层);章节直达工作台,其余走互链枢纽 */}
        <SearchBox pid={pid}
          onGoChapter={(nid) => goTask("workbench", nid)}
          onJumpEntity={jumpEntity} />
        {/* 二期②写作区 B:写作模式=中栏占满(左右栏暂时隐藏) */}
        <button className={expanded === "center" ? "active" : ""}
          title="写作模式:中栏占满内容区,左右栏暂时隐藏"
          onClick={() => setExpanded(expanded === "center" ? null : "center")}>
          {expanded === "center" ? "✍ 写作模式还原" : "✍ 写作模式"}
        </button>
        {/* 阅读模式(候选清单落地批 B):全屏连续阅读定稿/全部章 */}
        <button title="阅读模式:全屏连续阅读(可切仅定稿;Esc 退出)"
          onClick={() => setReadingMode(true)}>📖 阅读模式</button>
        <span className="row">
          <button title="收起/展开左栏(Alt+1)" onClick={() => setLeftOpen(!leftOpen)}>{leftOpen ? "⟨ 收左栏" : "⟩ 展左栏"}</button>
          <button title="左栏占满内容区/还原(小面板先全屏再开抽屉,互不遮挡)"
            onClick={() => setExpanded(expanded === "left" ? null : "left")}>
            {expanded === "left" ? "⟨ 左栏还原" : "⟨⟨ 左栏全屏"}
          </button>
          <button title="右栏占满内容区/还原(小面板先全屏再开抽屉,互不遮挡)"
            onClick={() => setExpanded(expanded === "right" ? null : "right")}>
            {expanded === "right" ? "右栏还原 ⟩" : "右栏全屏 ⟫"}
          </button>
          <button title="收起/展开右栏(Alt+2)" onClick={() => setRightOpen(!rightOpen)}>{rightOpen ? "收右栏 ⟩" : "展右栏 ⟩"}</button>
        </span>
      </div>

      {readingMode && <ReadingMode pid={pid} onClose={() => setReadingMode(false)} />}

      <div className="book3" style={{ gridTemplateColumns: colDefs }}>
        {leftOpen && expanded !== "right" && expanded !== "center" && (
        <aside className="book3-col left">
          <div className="col-switch">
            {LEFT_PANELS.map((t) => (
              <button key={t.key} className={leftPanel === t.key ? "active" : ""}
                onClick={() => setLeftPanel(t.key)}>{t.label}</button>
            ))}
          </div>
          <div className="col-body">
            {msg && <p className="ok">{msg}</p>}
            {leftPanel === "outline" && <OutlinePanel pid={pid} onGoPanel={goTask} onShowLinks={showLinks} onAskAI={askAI} openNodeId={pendingNode} />}
            {leftPanel === "l1" && <L1Panel pid={pid} onShowLinks={showLinks} />}
            {leftPanel === "ideas" && (
              <IdeaPanel pid={pid} drillTarget={ideaTarget} onConsumedDrill={() => setIdeaTarget(null)} />
            )}
            {leftPanel === "info" && (
              <div>
                {editing ? (
                  <BookEdit book={book} onSaved={() => { setEditing(false); load(); }} onCancel={() => setEditing(false)} />
                ) : (
                  <>
                    <dl className="info-grid">
                      <div><dt>主角</dt><dd>{book.protagonist || "—"}</dd></div>
                      <div><dt>类型</dt><dd>{book.genre || "—"}</dd></div>
                      <div><dt>受众</dt><dd>{book.audience || "—"}</dd></div>
                      <div><dt>情节结构</dt><dd>{book.plot_mode || "—"}</dd></div>
                      <div><dt>力量体系预设</dt><dd>{book.power_preset || "—"}</dd></div>
                      <div><dt>金手指预设</dt><dd>{book.cheat_preset || "—"}</dd></div>
                      <div><dt>每章字数</dt><dd>{book.chapter_words ?? "—"}</dd></div>
                      <div><dt>目标总字数</dt><dd>{book.target_words ?? "—"}</dd></div>
                    </dl>
                    {book.core_conflict && <p><b>核心冲突:</b>{book.core_conflict}</p>}
                    {book.description && <p><b>简介:</b>{book.description}</p>}
                    <button onClick={() => setEditing(true)}>编辑向导信息</button>
                  </>
                )}
                <div className="stat-strip">
                  <span>正式档案:{Object.values(counts).reduce((a, c) => a + (c.confirmed ?? 0), 0)} 条</span>
                  <span>待批准提案:{Object.values(counts).reduce((a, c) => a + (c.proposal ?? 0), 0)} 条</span>
                  {outlineStats && <span>大纲:{outlineStats.vol} 卷 / {outlineStats.ch} 章(定稿 {outlineStats.fin})</span>}
                </div>
                <div className="quick-actions">
                  <button onClick={() => setCenterMode("chat")}>💬 对话台</button>
                  <button onClick={() => goTask("workbench")}>⚒ 写章</button>
                  <button onClick={() => goTask("review")}>📄 终审</button>
                  <button onClick={() => setWidePanel("dashboard")}>📊 书况台</button>
                  <button onClick={() => { setLeftPanel("l1"); setLeftOpen(true); }}>🗂 档案库</button>
                  {/* 批次三①续件:全书导出(用户拍板文件类型=txt/md 两种) */}
                  <button title="按章节顺序导出全书正文(md)" onClick={() => window.open(`/api/books/${pid}/export?fmt=md`, "_blank")}>⬇ 导出 md</button>
                  <button title="按章节顺序导出全书正文(txt)" onClick={() => window.open(`/api/books/${pid}/export?fmt=txt`, "_blank")}>⬇ 导出 txt</button>
                  {/* 批次四③:书=目录工作区(md 镜像,DB 唯一真源;外部改动走文本导入闸门收回) */}
                  <button title="全书结构镜像到 data/books/<书名>/(正文/设定/大纲/时间线)" onClick={() =>
                    api.mirrorBook(pid).then((r) => { setMsg(`书目录已同步:${r.dir}(${r.files} 个文件)`); setTimeout(() => setMsg(""), 4000); }).catch((e) => setError(String((e as Error).message || e)))
                  }>📂 同步书目录</button>
                  <button title="在资源管理器中打开书目录(需先同步)" onClick={() =>
                    api.openBookFolder(pid).catch((e) => setError(String((e as Error).message || e)))
                  }>📂 打开书目录</button>
                </div>
                <div className="row">
                  <span className="muted small">单本书默认技能(优先级:单本书 &gt; 全局 &gt; 不启用):</span>
                  <select
                    value={skillCfg?.override === null || skillCfg === null ? FOLLOW_GLOBAL : skillCfg.override}
                    onChange={(e) => setBookSkill(e.target.value)}
                  >
                    <option value={FOLLOW_GLOBAL}>
                      跟随全局{skillCfg?.global ? `(当前:${skillName(skillCfg.global)})` : "(当前:不启用)"}
                    </option>
                    <option value="">不启用</option>
                    {skills.map((s) => (
                      <option key={s.key} value={s.key}>{s.name}</option>
                    ))}
                  </select>
                  <span className="muted small">
                    当前生效:{skillCfg ? (skillCfg.effective ? skillName(skillCfg.effective) : "不启用") : "…"}
                    {skillCfg?.override != null && "(本书覆盖)"}
                  </span>
                </div>
                <p className="muted small">
                  L1 各类:{" "}
                  {["worldview", "character", "power", "faction", "map", "item_economy"].map((c) =>
                    `${{ worldview: "世界观", character: "角色", power: "力量体系", faction: "势力阵营", map: "地图", item_economy: "物品经济" }[c]} ${confirmed(c)}(+${proposals(c)}提案)`
                  ).join(" / ")}
                </p>
              </div>
            )}
          </div>
        </aside>
        )}

        {leftOpen && expanded !== "right" && expanded !== "center" && (
        <div className="col-splitter" title="左右拖动调宽左栏"
          onPointerDown={startDrag("l")} />
        )}

        <section className="book3-center" style={expanded && expanded !== "center" ? { display: "none" } : undefined}>
          {centerMode === "chat" ? (
            <div className="col-body">
              <ChatPanel
                key={chatNonce}
                projectId={pid}
                ownerType="book"
                ownerId={pid}
                defaultSessionName="书级对话"
                allowPresets
                presets={BOOK_PRESETS}
                initialPreset={chatPreset}
                onOpenNode={openSugNode}
                allowSkill
                allowRefs
                emptyHint="书级对话:上下文 = 书信息 + 大纲概要 + 近期章节 + L1 常驻。可闲聊可出建议块,建议逐条走采纳闸门;新书写完向导,先点下方方向卡起步。"
              />
            </div>
          ) : (
            <div className="col-body">
              {taskPanel === "workbench" && <WorkbenchPanel pid={pid} initialNodeId={taskTarget} />}
              {taskPanel === "review" && <ReviewPanel pid={pid} initialNodeId={taskTarget} />}
            </div>
          )}
        </section>

        {rightOpen && expanded !== "left" && expanded !== "center" && (
        <div className="col-splitter" title="左右拖动调宽右栏"
          onPointerDown={startDrag("r")} />
        )}

        {rightOpen && expanded !== "left" && expanded !== "center" && (
        <aside className="book3-col right">
          <div className="col-switch">
            {RIGHT_PANELS.filter((t) => RIGHT_PRIMARY.includes(t.key)).map((t) => (
              <button key={t.key} className={rightPanel === t.key ? "active" : ""}
                onClick={() => setRightPanel(t.key)}>{t.label}</button>
            ))}
            {(() => {
              const over = RIGHT_PANELS.filter((t) => !RIGHT_PRIMARY.includes(t.key));
              const activeOver = over.find((t) => t.key === rightPanel);
              return over.length > 0 && (
                <span className="more-menu">
                  <button className={activeOver ? "active" : ""}
                    onClick={() => setMoreOpen(!moreOpen)}>
                    {activeOver ? activeOver.label : "更多 ▾"}
                  </button>
                  {moreOpen && (
                    <div className="more-menu-pop" onClick={() => setMoreOpen(false)}>
                      {over.map((t) => (
                        <button key={t.key} className={rightPanel === t.key ? "active" : ""}
                          onClick={() => setRightPanel(t.key)}>{t.label}</button>
                      ))}
                    </div>
                  )}
                </span>
              );
            })()}
          </div>
          <div className="col-body">
            {rightPanel === "graphs" && <GraphCenterPanel pid={pid} onShowLinks={showLinks} />}
            {rightPanel === "outcanvas" && <OutlineCanvasPanel pid={pid} onShowLinks={showLinks} />}
            {rightPanel === "timeline" && <TimelinePanel pid={pid} onShowLinks={showLinks} />}
            {rightPanel === "reviewcard" && <ReviewCardPanel pid={pid} />}
            {WIDE_PANELS.some((w) => w.key === rightPanel) && (
              <div className="wide-entry-cards">
                {WIDE_PANELS.map((w) => (
                  <button key={w.key} className="wide-entry-card"
                    onClick={() => setWidePanel(w.key)}>
                    <span className="wide-entry-icon">{w.icon}</span>
                    <span>
                      <b>{w.label}</b>
                      <span className="small muted">{w.desc}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>
        )}
      </div>

      {widePanel && (
        <div className="wide-overlay" onClick={() => setWidePanel(null)}>
          <div className="wide-win" onClick={(e) => e.stopPropagation()}>
            <div className="row spread">
              <b>{WIDE_PANELS.find((w) => w.key === widePanel)?.label}</b>
              <button className="link" onClick={() => setWidePanel(null)}>关闭 ✕</button>
            </div>
            <div className="wide-body">
              {widePanel === "dashboard" && <DashboardPanel pid={pid} onGoPanel={goTask} />}
              {widePanel === "l2board" && <L2BoardPanel pid={pid} />}
              {widePanel === "chaishu" && <ChaishuPanel pid={pid} />}
            </div>
          </div>
        </div>
      )}

      {linksTarget && (
        <EntityDrawer
          pid={pid}
          etype={linksTarget.etype}
          id={linksTarget.id}
          title={linksTarget.title}
          onClose={() => setLinksTarget(null)}
          onJump={jumpEntity}
        />
      )}
    </div>
  );
}

function BookEdit({
  book,
  onSaved,
  onCancel,
}: {
  book: Book;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [d, setD] = useState({
    name: book.name,
    genre: book.genre ?? "",
    protagonist: book.protagonist ?? "",
    audience: book.audience ?? "",
    core_conflict: book.core_conflict ?? "",
    description: book.description ?? "",
    chapter_words: book.chapter_words?.toString() ?? "",
    target_words: book.target_words?.toString() ?? "",
  });
  const [err, setErr] = useState("");   // 批次七④:原生 alert 换行内错误条(内嵌面板 alert 同样挂命令通道)
  const set = (k: keyof typeof d, v: string) => setD({ ...d, [k]: v });

  const save = async () => {
    setErr("");
    try {
      await api.updateBook(book.id, {
        name: d.name,
        genre: d.genre || null,
        protagonist: d.protagonist || null,
        audience: d.audience || null,
        core_conflict: d.core_conflict || null,
        description: d.description || null,
        chapter_words: d.chapter_words ? Number(d.chapter_words) : null,
        target_words: d.target_words ? Number(d.target_words) : null,
      });
      onSaved();
    } catch (e: unknown) {
      setErr(String((e as Error).message || e));
    }
  };

  return (
    <div className="form">
      {err && <p className="error">{err}</p>}
      <label>书名 *<input value={d.name} onChange={(e) => set("name", e.target.value)} /></label>
      <label>主角<input value={d.protagonist} onChange={(e) => set("protagonist", e.target.value)} /></label>
      <label>类型<input value={d.genre} onChange={(e) => set("genre", e.target.value)} /></label>
      <label>受众<input value={d.audience} onChange={(e) => set("audience", e.target.value)} /></label>
      <label>每章字数<input type="number" value={d.chapter_words} onChange={(e) => set("chapter_words", e.target.value)} /></label>
      <label>目标总字数<input type="number" value={d.target_words} onChange={(e) => set("target_words", e.target.value)} /></label>
      <label className="full">核心冲突<textarea rows={2} value={d.core_conflict} onChange={(e) => set("core_conflict", e.target.value)} /></label>
      <label className="full">简介<textarea rows={2} value={d.description} onChange={(e) => set("description", e.target.value)} /></label>
      <div className="row">
        <button onClick={onCancel}>取消</button>
        <button className="primary" onClick={save}>保存</button>
      </div>
    </div>
  );
}
