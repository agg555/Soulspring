"""M0-5: 从旧系统 cherrystudio.sqlite 备份库提取混沌/初绽提示词(剥离一切 API key)。

来源: E:\\小说【神陨之地】\\cherry备份\\cherry-studio.202608111444.zip
     → Data/cherrystudio.sqlite 的 agent 表(name=混沌 instructions=9223字 / name=初绽 instructions=6189字)
     与任务书 §7 缺件表记载的字数一致,确认为本体。

安全纪律(任务书缺件表): 提取物中不得有任何 API key,逐字段正则核对后才落盘。
key 实际存放处 = 同库 mcp_server 表 env 字段(如 TAVILY_API_KEY/BOCHA_API_KEY),本脚本不读取不导出。
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.llm.atomic_io import write_text_atomic  # noqa: E402

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")

# 覆盖常见云厂商 key 形态 + 智谱 id.secret 形态 + 通用长随机串
KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"tvly-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"xox[bpars]-[A-Za-z0-9-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{32}\.[A-Za-z0-9_-]{8,}\b"),  # 智谱 key 形态
    re.compile(r"\b[A-Za-z0-9]{40,}\b"),  # 通用超长随机串(保守兜底)
]

FIELDS = ["instructions", "description"]  # 逐字段核对清单


def scrub(text: str) -> tuple[str, list[str]]:
    hits = []
    for pat in KEY_PATTERNS:
        for m in pat.finditer(text):
            hits.append(m.group(0)[:12] + "…")
    out = text
    for pat in KEY_PATTERNS:
        out = pat.sub("***已剥除疑似密钥***", out)
    return out, hits


def main() -> None:
    db = os.path.join(os.environ["TEMP"], "inspect_cherrystudio.sqlite")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    agents = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM agent")}

    for name, char_len in [("混沌", 9223), ("初绽", 6189)]:
        row = agents.get(name)
        if not row:
            print(f"[FAIL] agent 表中无 {name}")
            sys.exit(1)
        body = row["instructions"] or ""
        if abs(len(body) - char_len) > 50:
            print(f"[WARN] {name} instructions {len(body)} 字,与记载 {char_len} 字偏差较大")

        desc, d_hits = scrub(row["description"] or "")
        body2, b_hits = scrub(body)
        all_hits = d_hits + b_hits

        # 落盘前最终核验:扫一遍成品,必须零命中
        provenance = (
            f"# {name}提示词(旧系统平移)\n\n"
            f"> 提取自旧系统 CherryStudio 备份库 cherrystudio.sqlite 的 agent 表"
            f"(2026-08-30 由 Soulspring M0-5 脚本提取)。\n"
            f"> 提取时逐字段正则核对,发现并剥除疑似密钥 {len(all_hits)} 处;成品复扫零命中。\n\n"
            f"## 助手描述\n\n{desc}\n\n## 系统提示词全文\n\n"
        )
        final = provenance + body2
        residual = [p for p in KEY_PATTERNS if p.search(final)]
        if residual:
            print(f"[FAIL] {name} 成品仍有密钥形态残留")
            sys.exit(1)

        out_path = os.path.join(PROMPTS_DIR, f"{name}-提示词.md")
        write_text_atomic(out_path, final)
        print(f"[OK] {name}: {len(body)} 字 → prompts/{name}-提示词.md"
              f"(剥除疑似密钥 {len(all_hits)} 处)")

    conn.close()


if __name__ == "__main__":
    main()
