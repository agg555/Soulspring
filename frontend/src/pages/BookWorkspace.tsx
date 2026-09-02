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

const TABS = [
  { key: "info", label: "书籍信息" },
  { key: "l1", label: "L1 档案库" },
  { key: "outline", label: "大纲树" },
  { key: "workbench", label: "写章工作台" },
  { key: "review", label: "终审对话台" },
  { key: "dashboard", label: "驾驶舱" },
  { key: "timeline", label: "剧情时间线" },
  { key: "graphs", label: "图谱中心" },
  { key: "l2board", label: "L2 看板" },
  { key: "chaishu", label: "拆书官" },
] as const;

const FOLLOW_GLOBAL = "__follow_global__";   // 下拉哨兵值:移除单本书覆盖,回到全局默认

export default function BookWorkspace({
  pid,
  onBack,
}: {
  pid: string;
  onBack: () => void;
}) {
  const [book, setBook] = useState<Book | null>(null);
  const [counts, setCounts] = useState<Record<string, Record<string, number>>>({});
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("info");
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

  return (
    <div>
      <div className="row spread">
        <button onClick={onBack}>← 返回书架</button>
        <span className="muted small">F0 向导信息 · 第 2 周建书范围</span>
      </div>
      <h2>{book.name}</h2>
      <p className="muted small">
        {[book.genre, book.audience, ...(book.tropes ?? []), ...(book.style ?? [])]
          .filter(Boolean).join(" · ") || "尚未填写类型与风格"}
      </p>

      <nav className="subnav">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
            {t.key === "l1" && Object.values(counts).some((c) => (c.proposal ?? 0) > 0) && (
              <span className="badge warn">有提案</span>
            )}
          </button>
        ))}
      </nav>

      <div className="workspace-section">
        {msg && <p className="ok">{msg}</p>}
        {tab === "info" && (
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
        {tab === "l1" && <L1Panel pid={pid} />}
        {tab === "outline" && <OutlinePanel pid={pid} onGoPanel={(t) => setTab(t)} />}
        {tab === "workbench" && <WorkbenchPanel pid={pid} />}
        {tab === "review" && <ReviewPanel pid={pid} />}
        {tab === "dashboard" && <DashboardPanel pid={pid} />}
        {tab === "timeline" && <TimelinePanel pid={pid} />}
        {tab === "graphs" && <GraphCenterPanel pid={pid} />}
        {tab === "l2board" && <L2BoardPanel pid={pid} />}
        {tab === "chaishu" && <ChaishuPanel pid={pid} />}
      </div>
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
