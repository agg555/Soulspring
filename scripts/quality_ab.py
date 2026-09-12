"""二期⑧:生成质量调优实验——8a build_proposal 降档 A/B(GLM max vs high)+
8b 温度三档样章对比(deepseek 稳健/标准/灵感)。结论入执行记录与设置页。

运行前提:先 `llm_switch('glm')`(8a 需要 reasoning_effort 注入,DeepSeek 无档位
差异)。8b 在当前三件套(deepseek)下跑即可,温度经 llm.top_p/temperature 生效。
成本预估:2 次 GLM 构建(¥0.02 级)+ 3 次 deepseek 草稿(¥0.05 级),合计 ≪¥1。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.common import _prompt  # noqa: E402
from app.assembly import assembled_text, build_assembly  # noqa: E402
from app.audit.anti_ai import build_anti_ai_prompt_section  # noqa: E402
from app.ledger.usage import chat_completion  # noqa: E402
from app.routers.settings_api import SwitchIn, llm_switch  # noqa: E402
from app.settings_store import update_settings  # noqa: E402

BOOK = sys.argv[1] if len(sys.argv) > 1 else ""
NID = sys.argv[2] if len(sys.argv) > 2 else ""


def set_effort(effort: str) -> None:
    update_settings("thinking", {"by_action": {"build_proposal": effort}})


def ab_build(pid: str) -> list[dict]:
    from app.routers.build import build_propose
    out = []
    for effort in ("max", "high"):
        set_effort(effort)
        t0 = time.monotonic()
        try:
            r = build_propose(pid)
            dt = round(time.monotonic() - t0, 1)
            u = r["usage"]
            out.append({"effort": effort, "ok": True, "seconds": dt,
                        "count": r["count"], "parsed_raw": r["parsed_raw"],
                        "dropped": r["dropped"], "cost": u["cost_total"],
                        "out_tokens": u["response_tokens"],
                        "req_tokens": u["request_tokens"]})
        except Exception as exc:  # noqa: BLE001 实验记录失败也是结论
            out.append({"effort": effort, "ok": False,
                        "seconds": round(time.monotonic() - t0, 1),
                        "error": str(exc)[:200]})
    return out


def temp_samples(pid: str, nid: str) -> list[dict]:
    """同一章、同一装配,仅温度档位不同,各出一版开篇(截 500 字对比)。"""
    from app.settings_store import get_settings, update_settings
    presets = [("steady", 0.5, None), ("standard", 0.7, None), ("inspire", 1.0, 0.95)]
    out = []
    for key, temp, top_p in presets:
        update_settings("llm", {"temperature": temp, "top_p": top_p})
        asm = build_assembly(pid, nid, log=False)
        style = ""
        r = chat_completion(
            [{"role": "system", "content": _prompt("章节-草稿.md", {
                "{{ASSEMBLED}}": assembled_text(asm), "{{STYLE}}": style,
                "{{ANTI_AI}}": build_anti_ai_prompt_section(),
                "{{PLAN}}": "{}", "{{MIN}}": "1500", "{{MAX}}": "3000"})},
             {"role": "user", "content": "开始撰写本章正文。"}],
            action="chapter_draft", project_id=pid, node_id=nid,
            agent_type="writer", input_summary=f"温度样章:{key}")
        out.append({"preset": key, "temperature": temp, "top_p": top_p,
                    "chars": len(r["content"]), "seconds": round(r["duration_ms"] / 1000, 1),
                    "cost": r["usage"]["cost_total"],
                    "sample": r["content"].strip()[:500]})
    return out


if __name__ == "__main__":
    print("== 切换 GLM(8a 需要 reasoning_effort 差异)==", flush=True)
    llm_switch(SwitchIn(provider="glm"))
    from app.settings_store import get_settings
    print("当前:", get_settings()["llm"]["model"], flush=True)
    print("== 8a build_proposal A/B(max vs high)==", flush=True)
    ab = ab_build(BOOK)
    for row in ab:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print("== 切回 deepseek(8b 样章)==", flush=True)
    llm_switch(SwitchIn(provider="deepseek"))
    print("== 8b 温度三档样章 ==", flush=True)
    ts = temp_samples(BOOK, NID)
    for row in ts:
        print("----", row["preset"], f"temp={row['temperature']} top_p={row['top_p']}",
              f"{row['chars']}字 {row['seconds']}s ¥{row['cost']}", flush=True)
        print(row["sample"], flush=True)
    # 收尾:温度回标准档(结论由用户/记录决定是否改默认)
    update_settings("llm", {"temperature": 0.7, "top_p": None})
    print("温度已回标准档;build_proposal 档位未固化(见结论拍板)", flush=True)
