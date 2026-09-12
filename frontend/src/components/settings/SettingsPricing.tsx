import type { Settings } from "../../types";

/**
 * 设置页·价格区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 价格基准(默认价/正价/折扣截止)与单章预算告警线只读提示。
 */
export default function SettingsPricing({
  s, patchDefaultPrice, patchStandardPrice, patchDiscountUntil, savePricing,
}: {
  s: Settings;
  patchDefaultPrice: (field: "input_per_m" | "output_per_m", value: string) => void;
  patchStandardPrice: (field: "input_per_m" | "output_per_m", value: string) => void;
  patchDiscountUntil: (value: string) => void;
  savePricing: () => void;
}) {
  return (
    <details className="set-sec">
      <summary>价格基准（元 / 百万 token）</summary>
      <div className="form">
        <label>
          默认输入价
          <input
            type="number"
            step="0.01"
            value={s.pricing.default.input_per_m}
            onChange={(e) => patchDefaultPrice("input_per_m", e.target.value)}
          />
        </label>
        <label>
          默认输出价
          <input
            type="number"
            step="0.01"
            value={s.pricing.default.output_per_m}
            onChange={(e) => patchDefaultPrice("output_per_m", e.target.value)}
          />
        </label>
        <label>
          折扣截止日(含当天,过期自动按正价计)
          <input
            type="date"
            value={s.pricing.discount_until ?? ""}
            onChange={(e) => patchDiscountUntil(e.target.value)}
          />
        </label>
        <button onClick={savePricing}>保存价格基准</button>
        <label>
          正价输入(到期自动启用)
          <input
            type="number"
            step="0.01"
            value={s.pricing.standard?.input_per_m ?? ""}
            onChange={(e) => patchStandardPrice("input_per_m", e.target.value)}
          />
        </label>
        <label>
          正价输出(到期自动启用)
          <input
            type="number"
            step="0.01"
            value={s.pricing.standard?.output_per_m ?? ""}
            onChange={(e) => patchStandardPrice("output_per_m", e.target.value)}
          />
        </label>
      </div>
      <p className="muted">
        单章预算告警线:¥{s.budget.per_chapter_alert}(任务书 §6)。0.25 元线的标定依赖真实价格,运行期校准。
      </p>
    </details>
  );
}
