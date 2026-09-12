/**
 * 设置页·关于区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 关于 Soulspring 与更新日志——两块纯静态文案,无 props。
 */
export default function SettingsAbout() {
  return (
    <>
      <details className="set-sec">
        <summary>关于 Soulspring</summary>
      <div className="card" style={{ flex: "none" }}>
        <p style={{ margin: "0 0 6px" }}>
          <b>Soulspring</b> <span className="muted small">公开基础版 v1.0 已发布 · 商业化主线 v2.0-dev(版本落后策略见边界文档)</span>
        </p>
        <p className="muted small" style={{ margin: "0 0 6px" }}>
          本地单用户的 AI 长篇协作工作台:人主编 99%,AI 出建议走闸门,正文决定权永远在人。
          薄 UI 零框架、零遥测;数据 SQLite 本地存,git 即备份。
        </p>
        <p className="muted small" style={{ margin: 0 }}>
          开源参考:inkflow / chevoink 契约(MIT,见 THIRD-PARTY-NOTICES.md);设计令牌体系参考 shadcn/ui(MIT)。
        </p>
      </div>
      </details>
      <details className="set-sec">
        <summary>更新日志</summary>
        <ul className="changelog set-pad">
        <li><b>批次七(2026-09-08)</b> — 分层搜索(千章子串 ≤1s)/ 任务过程时间线 / 行内确认统一收尾 / 模板双层(题材包+我的模板)/ 千章图谱 LOD(默认收起+远景只画框)/ 统计分列与日时粒度 / 设计令牌 / 全套界面抛光。</li>
        <li><b>批次六(2026-09-07)</b> — 子 agent 化与细节延展;触点四件套(模型/上限/追加词分动作生效)。</li>
        <li><b>批次五(2026-09-06)</b> — 画布对齐与千章实测;模型切换器;峰谷价记账。</li>
        <li><b>批次四(2026-09-05)</b> — 统一图谱引擎(十类一板)/ 前后端工程加固(锁版本/CSRF/Origin)。</li>
        <li><b>更早</b> — 三栏工作区 / 写章工作台完整管道 / 拆书官 / 书况台 / 多线会话与建议采纳闸门。</li>
      </ul>
      </details>
    </>
  );
}
