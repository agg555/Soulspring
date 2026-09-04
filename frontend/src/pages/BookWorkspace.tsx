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
import GraphCenterPanel from "./GraphCenterPanel";
import ChatPanel from "../components/ChatPanel";
import EntityDrawer from "../components/EntityDrawer";

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
] as const;
const RIGHT_PANELS = [
  { key: "graphs", label: "图谱中心" },
  { key: "dashboard", label: "书况台" },
  { key: "timeline", label: "剧情时间线" },
  { key: "l2board", label: "L2 看板" },
  { key: "chaishu", label: "拆书官" },
] as const;
const TASK_PANELS = [
  { key: "workbench", label: "写章工作台" },
  { key: "review", label: "终审对话台" },
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
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [linksTarget, setLinksTarget] = useState<{ etype: string; id: string; title: string } | null>(null);
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
  const goTask = (t: "workbench" | "review") => { setTaskPanel(t); setCenterMode("task"); };

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
        <span className="row" style={{ margin: "0 0 0 auto" }}>
          <button title="收起/展开左栏" onClick={() => setLeftOpen(!leftOpen)}>{leftOpen ? "⟨ 收左栏" : "⟩ 展左栏"}</button>
          <button title="收起/展开右栏" onClick={() => setRightOpen(!rightOpen)}>{rightOpen ? "收右栏 ⟩" : "展右栏 ⟩"}</button>
        </span>
      </div>

      <div className={`book3 ${leftOpen ? "" : "no-left"} ${rightOpen ? "" : "no-right"}`}>
        <aside className="book3-col left">
          <div className="col-switch">
            {LEFT_PANELS.map((t) => (
              <button key={t.key} className={leftPanel === t.key ? "active" : ""}
                onClick={() => setLeftPanel(t.key)}>{t.label}</button>
            ))}
          </div>
          <div className="col-body">
            {msg && <p className="ok">{msg}</p>}
            {leftPanel === "outline" && <OutlinePanel pid={pid} onGoPanel={goTask} onShowLinks={showLinks} />}
            {leftPanel === "l1" && <L1Panel pid={pid} onShowLinks={showLinks} />}
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

        <section className="book3-center">
          {centerMode === "chat" ? (
            <div className="col-body">
              <ChatPanel
                projectId={pid}
                ownerType="book"
                ownerId={pid}
                defaultSessionName="书级对话"
                allowPresets
                presets={BOOK_PRESETS}
                allowSkill
                allowRefs
                emptyHint="书级对话:上下文 = 书信息 + 大纲概要 + 近期章节 + L1 常驻。可闲聊可出建议块,建议逐条走采纳闸门;新书写完向导,先点下方方向卡起步。"
              />
            </div>
          ) : (
            <div className="col-body">
              {taskPanel === "workbench" && <WorkbenchPanel pid={pid} />}
              {taskPanel === "review" && <ReviewPanel pid={pid} />}
            </div>
          )}
        </section>

        <aside className="book3-col right">
          <div className="col-switch">
            {RIGHT_PANELS.map((t) => (
              <button key={t.key} className={rightPanel === t.key ? "active" : ""}
                onClick={() => setRightPanel(t.key)}>{t.label}</button>
            ))}
          </div>
          <div className="col-body">
            {rightPanel === "graphs" && <GraphCenterPanel pid={pid} onShowLinks={showLinks} />}
            {rightPanel === "dashboard" && <DashboardPanel pid={pid} />}
            {rightPanel === "timeline" && <TimelinePanel pid={pid} onShowLinks={showLinks} />}
            {rightPanel === "l2board" && <L2BoardPanel pid={pid} />}
            {rightPanel === "chaishu" && <ChaishuPanel pid={pid} />}
          </div>
        </aside>
      </div>

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
  const set = (k: keyof typeof d, v: string) => setD({ ...d, [k]: v });

  const save = async () => {
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
      alert(String((e as Error).message || e));
    }
  };

  return (
    <div className="form">
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
