import { useState } from "react";

/**
 * 命名工坊(候选清单落地批 B,纯前端零 LLM):随机中文姓名生成。
 * 姓氏池(常见+网文常用复姓)× 风格名字池;点击名字复制。写书起名辅助,
 * 不做任何 AI 调用与落库。
 */
const SURNAMES = "李王张刘陈杨黄赵吴周徐孙马朱胡郭何林罗高郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦傅方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤慕容欧阳上官司徒诸葛司马东方独孤南宫令狐".split("");
const GIVEN: Record<string, string[]> = {
  现代: "雨晨子墨思远若彤浩然欣怡俊杰静怡明轩梓萱天佑诗涵铭泽雨桐博文可馨嘉懿语嫣泽宇梦琪".split(""),
  武侠: "剑锋寒霜傲天涯孤鸿青云无极逍遥铁山残阳飞雪听风惊鸿落雁断岳流云追命拂衣问天醉月".split(""),
  玄幻: "玄冥星辰紫霄苍穹焚天擎苍月寂灭灵溪冰璃焰阳青冥云篆风华雷泽千羽霜华夜白黎渊".split(""),
  都市: "晨曦志强丽娜建国晓东婷婷丽华军伟秀英海燕国庆淑芬志明春花美玲德华秋婷".split(""),
};

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function genName(style: string, twoCharGiven: boolean): string {
  const surname = pick(SURNAMES);
  const pool = GIVEN[style] ?? GIVEN["现代"];
  const given = twoCharGiven
    ? (pick(pool) + pick(pool))
    : pick(pool);
  return surname + given;
}

export default function NamingStudio() {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState("现代");
  const [twoChar, setTwoChar] = useState(true);
  const [names, setNames] = useState<string[]>([]);
  const [copied, setCopied] = useState("");

  const roll = () => setNames(Array.from({ length: 10 }, () => genName(style, twoChar)));
  const copy = async (n: string) => {
    try {
      await navigator.clipboard.writeText(n);
      setCopied(n);
      setTimeout(() => setCopied(""), 1500);
    } catch { /* 剪贴板不可用忽略 */ }
  };

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <button className="link" title="随机中文名生成器(纯本地)"
        onClick={() => { setOpen(!open); if (names.length === 0) roll(); }}>
        🎲 命名工坊
      </button>
      {open && (
        <div className="dialog" style={{ position: "absolute", zIndex: 30, minWidth: 280 }}>
          <div className="row">
            <select value={style} onChange={(e) => setStyle(e.target.value)}>
              {Object.keys(GIVEN).map((k) => <option key={k} value={k}>{k}风</option>)}
            </select>
            <label className="row" style={{ margin: 0, gap: 4 }}>
              <input type="checkbox" checked={twoChar}
                onChange={(e) => setTwoChar(e.target.checked)} /> 双字名
            </label>
            <button className="link" onClick={roll}>🎲 再来十个</button>
            <button className="link" onClick={() => setOpen(false)}>收起</button>
          </div>
          <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
            {names.map((n, i) => (
              <button key={i} className="chip" title="点击复制"
                onClick={() => void copy(n)}>{n}</button>
            ))}
          </div>
          {copied && <p className="muted small">已复制「{copied}」</p>}
        </div>
      )}
    </span>
  );
}
