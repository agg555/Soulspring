"""anti_ai 结构类规则库回归(批次三算法体检,2026-09-06;零 LLM,纯离线)。"""
import tempfile
from pathlib import Path
import pytest
from app.audit.anti_ai import analyze_text, check_structural_rules, load_structural_rules


@pytest.fixture()
def tmp_db(monkeypatch):
    import app.db as dbmod
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(dbmod, "DATA_DIR", Path(tmp))
    monkeypatch.setattr(dbmod, "DB_PATH", Path(tmp) / "soulspring.db")
    dbmod._conn = None
    dbmod.migrate()
    yield dbmod
    dbmod._conn = None


def test_rules_load():
    rules = load_structural_rules()
    assert rules.get("connectives", {}).get("words")   # JSON 在且可解析


def test_structural_connectives_density():
    bad = "然而他笑了。仿佛在诉说什么。与此同时门开了。宿命般的一幕。值得玩味。" * 10
    out = check_structural_rules(bad)
    assert any("高频AI腔调词" in f for f in out)


def test_structural_parallelism():
    bad = "他一步一步走向高台。他一步一步握紧了拳。他一步一步抬起了头。风停了。"
    out = check_structural_rules(bad)
    assert any("连续排比" in f for f in out)


def test_structural_grand_summary():
    good_body = "陈昼推门进去,把伞放在门边,倒了杯水,坐下来,翻开了那份卷宗,看了很久。" * 5
    bad_tail = good_body + "这就是他的答案。那是一种无声的见证,意味着一切都将改变。"
    out = check_structural_rules(bad_tail)
    assert any("章尾升华腔" in f for f in out)


def test_clean_text_no_structural_findings():
    clean = ("陈昼把伞收了,靠在门边。雨还没停,他就着屋檐的水声把卷宗又翻了一遍。"
             "护士站的灯亮了一下,又暗下去。他没有抬头。")
    assert check_structural_rules(clean * 3) == []


def test_analyze_text_includes_structural():
    bad = "然而,与此同时,仿佛在诉说。宿命般的齿轮开始转动。值得玩味。" * 8
    out = analyze_text(bad)
    assert "structural_findings" in out and out["structural_findings"]


def test_price_for_cache_and_peak(tmp_db):
    """成本控制移植(2026-09-06):三元价+缓存拆分+峰谷窗口。"""
    from app.settings_store import update_settings
    from app.ledger.usage import _in_peak_window, log_usage, price_for
    from datetime import datetime
    update_settings("pricing", {
        "default": {"input_per_m": 1.5, "output_per_m": 4.5},
        "models": [{"model": "deepseek-v4-flash", "input_per_m": 1.5, "output_per_m": 4.5,
                    "cache_input_per_m": 0.05, "peak_input_per_m": 3.0,
                    "peak_output_per_m": 9.0, "peak_cache_input_per_m": 0.10,
                    "peak_schedule": "mon-fri 09-12,14-18"}],
    })
    # 终审修复 2026-09-07:峰谷价断言注入固时钟——原无参取真实时刻,周一 09-12/14-18
    # 峰窗内跑必碎("跨时段即碎",与 09-02"跨天即碎"同类)
    off_peak, on_peak = datetime(2026, 9, 5, 2, 0), datetime(2026, 9, 7, 10, 0)
    assert price_for("deepseek-v4-flash", now=off_peak) == (1.5, 4.5, 0.05)
    assert price_for("deepseek-v4-flash", now=on_peak) == (3.0, 9.0, 0.10)
    assert _in_peak_window("mon-fri 09-12,14-18", on_peak) is True
    assert _in_peak_window("mon-fri 09-12,14-18", off_peak) is False
    from app.ledger.usage import start_run
    rid = start_run("chat_test")
    row = log_usage(rid, provider="deepseek", model="deepseek-v4-flash",
                    action="chat_test", request_tokens=1_000_000, response_tokens=0,
                    duration_ms=1, cached_tokens=1_000_000, now=off_peak)
    assert abs(row["cost_total"] - 0.05) < 1e-9   # 全命中 → 只花缓存价
