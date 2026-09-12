"""M3 最小测试集:审计规则 / 装配上限 / 原子写(执行计划书 §8.2)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit.anti_ai import (  # noqa: E402
    analyze_text, check_banned_patterns, check_dash_count, cleanup_dashes,
)
from app.audit.code_checks import CodeChecker  # noqa: E402
from app.audit.world_state import (  # noqa: E402
    CharacterLite, CharacterMatrixLite, ForeshadowingLite, ResourceLedgerLite,
    ResourceLite, SubplotBoardLite, SubplotLite, BoundaryLite, WorldStateLite,
)


def make_ws(**kw) -> WorldStateLite:
    return WorldStateLite(
        characters=kw.get("characters", {}),
        resource_ledger=ResourceLedgerLite(kw.get("resources", {})),
        foreshadowing_pool=kw.get("foreshadowing", []),
        character_matrix=CharacterMatrixLite(kw.get("boundaries", {})),
        subplot_board=SubplotBoardLite(kw.get("subplots", [])),
        raw={},
    )


# ── 审计规则 ──

def test_dead_character_action_flagged():
    ws = make_ws(characters={"陈劫": CharacterLite(name="陈劫", status="dead")})
    text = "陈劫猛地转身，一刀劈向身后。" + "叙述" * 600
    r = CodeChecker().check_all(text, ws, chapter_number=2)
    assert any(i.category == "character_status" and i.severity == "critical" for i in r.issues)


def test_dead_character_flashback_not_flagged():
    ws = make_ws(characters={"陈劫": CharacterLite(name="陈劫", status="dead")})
    text = "他想起陈劫当年说过的话，恍如昨日。" + "叙述" * 600
    r = CodeChecker().check_all(text, ws, chapter_number=2)
    assert not any(i.category == "character_status" for i in r.issues)


def test_dead_character_dialogue_not_flagged():
    ws = make_ws(characters={"陈劫": CharacterLite(name="陈劫", status="dead")})
    text = "“陈劫当年可没这么客气。”他说。叙述" * 120
    r = CodeChecker().check_all(text, ws, chapter_number=2)
    assert not any(i.category == "character_status" for i in r.issues)


def test_consumed_resource_reappearance_flagged():
    ws = make_ws(resources={"r1": ResourceLite(key="r1", name="赤霄剑", owner="林晚", status="consumed")})
    text = "桌上摆着那柄赤霄剑。叙述" * 200
    r = CodeChecker().check_all(text, ws, chapter_number=5)
    assert any(i.category == "resource" and i.severity == "critical" for i in r.issues)
    assert all(i.auto_fixable for i in r.issues if i.category == "resource")


def test_consumed_resource_with_acquisition_ok():
    ws = make_ws(resources={"r1": ResourceLite(key="r1", name="赤霄剑", owner="林晚", status="consumed")})
    text = "他重新获得了赤霄剑。叙述" * 200
    r = CodeChecker().check_all(text, ws, chapter_number=5)
    assert not any(i.category == "resource" for i in r.issues)


def test_stale_foreshadowing_warned():
    ws = make_ws(foreshadowing=[ForeshadowingLite(detail="井底的铜镜秘密", planted_chapter=1, status="pending")])
    text = "叙述" * 600
    r = CodeChecker().check_all(text, ws, chapter_number=20)
    assert any(i.category == "foreshadowing" for i in r.issues)


def test_information_boundary_flagged():
    ws = make_ws(
        characters={"甲": CharacterLite(name="甲"), "乙": CharacterLite(name="乙")},
        boundaries={"甲": BoundaryLite(known_facts=["师父是被乙害死的"]), "乙": BoundaryLite(known_facts=[])},
    )
    # 甲知道的事实紧邻乙出现 → 乙疑似越界
    text = "乙走到院中，墙上传来一句低语：师父是被乙害死的。叙述" * 60
    r = CodeChecker().check_all(text, ws, chapter_number=3)
    assert any(i.category == "information_boundary" for i in r.issues)


def test_subplot_stagnation_flagged():
    ws = make_ws(subplots=[SubplotLite(name="漕帮恩怨", last_advanced=2, status="active")])
    text = "叙述" * 600
    r = CodeChecker().check_all(text, ws, chapter_number=10)
    assert any(i.category == "subplot" for i in r.issues)


# ── anti_ai ──

def test_dash_cleanup():
    text = "甲——乙——丙——丁——戊——己"
    assert check_dash_count(text) == 5
    cleaned = cleanup_dashes(text, max_dashes=4)
    assert check_dash_count(cleaned) == 4


def test_fatigue_and_banned_detected():
    text = "总之他赢了。总之他累了。总之都结束了。这不是勇气而是冲动。首先他起身，其次他佩刀，最后他出门。"
    a = analyze_text(text)
    assert a["fatigue_words"] and a["fatigue_words"][0][0] == "总之"
    assert any("不是" in p or "首先" in p for p in a["banned_patterns"])
    assert a["score"] < 100


def test_banned_pattern_recursion_safe():
    # 重复句式正则 (.){4,}\1 有灾难性回溯风险,验证无重复的正常文本可快速完成且不误报
    assert check_banned_patterns("他推门进来，把伞放在墙角，然后坐下了。") == []


# ── 原子写 ──

def test_atomic_write(tmp_path):
    from app.llm.atomic_io import write_json_atomic, write_text_atomic

    p = tmp_path / "a" / "b.json"
    write_json_atomic(p, {"k": "值"})
    assert p.read_text(encoding="utf-8") == '{\n  "k": "值"\n}'

    t = tmp_path / "x.txt"
    write_text_atomic(t, "正文")
    assert t.read_text(encoding="utf-8") == "正文"
