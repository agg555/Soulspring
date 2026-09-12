import { useState } from "react";

/**
 * 分列柱状图(二期②柱状图四修+悬浮;总览日/时 与 浮窗 24h 同族共用):
 * - 标签/柱对锚槽位中心(旧实现槽宽手算,标签错位);
 * - 末桶可标「现在」(nowLast);
 * - 跨天分隔线 + 昨/今标注(sepIndex/sepxLabels);
 * - 悬浮提示框(mouseenter,替代原生 <title>):日期/人工/AI/合计/AI 用时。
 */
export interface WcBucket {
  label: string;
  human: number;
  ai: number;
  aiMs?: number;
}

const fmtMs = (ms?: number) => {
  if (!ms) return "0s";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m${s % 60 ? `${s % 60}s` : ""}` : `${Math.floor(m / 60)}h${m % 60}m`;
};

export default function WcBars({ buckets, nowLast = false, sep = null, height = 70 }: {
  buckets: WcBucket[];
  nowLast?: boolean;                       // 末桶标签改「现在」
  sep?: { index: number } | null;          // 跨天分隔线索引(该槽前画虚线)
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = Math.max(1, buckets.length);
  const slot = 480 / n;
  const bw = Math.max(4, Math.min(30, slot * 0.36));
  const max = Math.max(10, ...buckets.flatMap((b) => [b.human, b.ai]));
  const barH = height - 26;
  const base = height - 14;
  const labelStep = Math.max(1, Math.ceil(n / 12));   // 标签抽稀(24 桶只标 1/4)

  return (
    <div className="wc-wrap">
      <svg viewBox={`0 0 480 ${height}`} className="wc-chart" role="img" aria-label="码字柱状图(人工/AI 分列)">
        {buckets.map((b, i) => {
          const cx = i * slot + slot / 2;                 // 槽位中心(柱与标签同锚)
          // 单边数据时单柱以槽位中心居中并加宽(2026-09-10 偏移复发根因:
          // 只有人工或只有 AI 时,旧实现仍按双边左右分列,可见柱偏在中心一侧)
          const both = b.human > 0 && b.ai > 0;
          const singleW = Math.min(bw * 1.8, slot * 0.5, 40);
          const hx = both ? cx - bw - 1 : cx - singleW / 2;
          const ax = both ? cx + 2 : cx - singleW / 2;
          const hh = (Math.max(b.human, 0) / max) * barH;
          const ha = (Math.max(b.ai, 0) / max) * barH;
          const label = nowLast && i === buckets.length - 1 ? "现在" : b.label;
          return (
            <g key={i}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((cur) => (cur === i ? null : cur))}>
              {/* 命中区(透明,覆盖整槽) */}
              <rect x={i * slot} y={0} width={slot} height={height} fill="transparent" />
              {b.human > 0 && (
                <rect x={hx} y={base - hh} width={both ? bw : singleW} height={hh} rx={2} fill="#9ece6a" />
              )}
              {b.ai > 0 && (
                <rect x={ax} y={base - ha} width={both ? bw : singleW} height={ha} rx={2} fill="#7aa2f7" opacity={0.85} />
              )}
              {sep && i === sep.index && (
                <line x1={i * slot} y1={2} x2={i * slot} y2={base + 2}
                  stroke="var(--muted)" strokeDasharray="3 3" strokeWidth={1} />
              )}
              {(i % labelStep === 0 || (nowLast && i === buckets.length - 1)) && (
                <text x={cx} y={height - 3} fontSize={9} textAnchor="middle" fill="var(--muted)">{label}</text>
              )}
            </g>
          );
        })}
        <line x1="0" y1={base} x2="480" y2={base} stroke="var(--border)" />
      </svg>
      {hover != null && buckets[hover] && (() => {
        const b = buckets[hover];
        const total = b.human + b.ai;
        return (
          <div className="wc-tip" style={{ left: `${((hover + 0.5) / n) * 100}%` }}>
            <b>{nowLast && hover === buckets.length - 1 ? "现在" : b.label}</b><br />
            人工 {b.human} 字 · AI {b.ai} 字 · 合计 {total} 字
            {b.aiMs != null && (<><br />AI 用时 {fmtMs(b.aiMs)}</>)}
          </div>
        );
      })()}
    </div>
  );
}
