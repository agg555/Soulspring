"""章节文本的确定性代码层审计。

移植自 inkflow(inkflow/pipeline/audit/code_checks.py,MIT License,
Copyright (c) 2026 ElysiaQWQ;详见 THIRD-PARTY-NOTICES.md)。
零 token 消耗;九类检查,产出带 evidence 的结构化问题清单。

检查类别:角色状态一致性 / 资源连续性 / 伏笔生命周期 / 信息边界 /
时间线一致性 / 子情节推进度 / 对话叙述比 / 字数合规 / anti-AI 扫描 /
去 AI 味质量信号(见 humanity.py,移植自 chevoink)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .anti_ai import check_banned_patterns, check_dialogue_ratio, check_fatigue_words
from .humanity import SIGNAL_LABELS, analyze_deterministic_quality
from .world_state import WorldStateLite

# 任务书检查协议要求的默认字数目标(规整器共用)
WORD_COUNT_MIN = 1500
WORD_COUNT_MAX = 3000
WORD_COUNT_TOLERANCE = 0.20


@dataclass
class CheckIssue:
    """单条审计问题。"""
    category: str           # character_status|resource|foreshadowing|information_boundary|timeline|subplot|style|word_count|anti_ai
    severity: str           # critical|warning|info
    dimension: str          # 人类可读维度名
    description: str
    suggestion: str = ""
    auto_fixable: bool = False
    evidence: str = ""      # 命中原文片段,供人复核/LLM 复核

    def to_dict(self) -> dict:
        return {
            "category": self.category, "severity": self.severity,
            "dimension": self.dimension, "description": self.description,
            "suggestion": self.suggestion, "auto_fixable": self.auto_fixable,
            "evidence": self.evidence,
        }


@dataclass
class CodeCheckResult:
    issues: list = field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0
    checks_total: int = 0
    humanity: object | None = None   # HumanityResult,去 AI 味质量信号(无 findings 时为有值的空结果)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def pass_rate(self) -> float:
        if self.checks_total == 0:
            return 1.0
        return self.checks_passed / self.checks_total

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0

    @property
    def passed(self) -> bool:
        return not self.has_critical

    def to_dict(self) -> dict:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "checks_total": self.checks_total,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "pass_rate": round(self.pass_rate, 2),
            "passed": self.passed,
            "humanity": self.humanity.to_dict() if self.humanity else None,
        }


class CodeChecker:
    """对章节正文 + 真相文件视图跑全部确定性检查。"""

    def check_all(self, chapter_text: str, world_state: WorldStateLite,
                  chapter_number: int, recent_texts: list[str] | None = None) -> CodeCheckResult:
        """recent_texts:近期章节正文,供跨章意象重复检测(可选,不传则只做本章内检测)。"""
        result = CodeCheckResult()

        self._check_character_status(chapter_text, world_state, result)
        self._check_resource_continuity(chapter_text, world_state, result)
        self._check_foreshadowing_lifecycle(chapter_text, world_state, chapter_number, result)
        self._check_information_boundaries(chapter_text, world_state, result)
        self._check_timeline_consistency(chapter_text, result)
        self._check_subplot_stagnation(world_state, chapter_number, result)
        self._check_dialogue_ratio(chapter_text, result)
        self._check_word_count(chapter_text, result)
        self._check_anti_ai(chapter_text, result)
        self._check_humanity(chapter_text, result, recent_texts)

        return result

    def _check_humanity(self, text: str, result: CodeCheckResult,
                        recent_texts: list[str] | None = None):
        """去 AI 味质量信号(零 token)。

        与 anti_ai 的区别:这里不做全局禁词,只报带原文证据的局部异常,
        且最高只到 warning——审美问题不做硬阻断(chevoink 23 号 §9.3)。
        """
        result.checks_total += 1
        hr = analyze_deterministic_quality(text, recent_texts)
        for f in hr.findings:
            result.issues.append(CheckIssue(
                category="humanity",
                severity=f.severity,
                dimension=SIGNAL_LABELS.get(f.signal, f.signal),
                description=f.description,
                suggestion=f.suggestion,
                auto_fixable=False,   # 审美类不做自动修,交给人裁决
                evidence=f.evidence,
            ))
        result.humanity = hr
        if hr.findings:
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 1. 角色状态一致性 ──
    def _check_character_status(self, text: str, ws: WorldStateLite, result: CodeCheckResult):
        """死亡/失踪角色不应再有主动行为;带闪回标记排除与对话排除降误报。"""
        result.checks_total += 1
        issues = []

        sentences = re.split(r"[。！？\n]", text)
        flashback_markers = ["回忆", "想起", "当年", "曾经", "过去", "那时", "记得"]
        verbs = "说|道|笑|喊|走|跑|看|拿|站|坐|点头|摇头|开口|转身|挥|踢|打|杀|攻击|握|拔|挡|闪|跳|扑|冲"

        for name, char in ws.characters.items():
            if char.status not in ("dead", "missing"):
                continue
            if name not in text:
                continue

            for sentence in sentences:
                if name not in sentence:
                    continue
                if self._is_in_dialogue(sentence, name):
                    continue
                if any(marker in sentence for marker in flashback_markers):
                    continue

                pattern = rf"{re.escape(name)}.{{0,15}}?({verbs})"
                match = re.search(pattern, sentence)
                if match:
                    idx = text.find(sentence)
                    ctx_start = max(0, idx - 100)
                    ctx_end = min(len(text), idx + len(sentence) + 100)
                    context = text[ctx_start:ctx_end]

                    issues.append(CheckIssue(
                        category="character_status",
                        severity="critical",
                        dimension="角色状态一致性",
                        description=f"角色「{name}」状态为 {char.status}，但疑似有主动行为",
                        suggestion=f"确认「{name}」是否真的在行动，或修改其状态",
                        auto_fixable=False,
                        evidence=context,
                    ))
                    break  # 每角色一条即可

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    def _is_in_dialogue(self, sentence: str, name: str) -> bool:
        """角色名只出现在引号内 = 对话提及,不算行动。"""
        quotes = re.findall(r"[“”「」『』](.*?)[“”「」『』]", sentence)
        for q in quotes:
            if name in q:
                non_dialogue = sentence
                for q2 in quotes:
                    non_dialogue = non_dialogue.replace(q2, "")
                if name not in non_dialogue:
                    return True
        return False

    # ── 2. 资源连续性 ──
    def _check_resource_continuity(self, text: str, ws: WorldStateLite, result: CodeCheckResult):
        """已丢失/消耗/损毁的资源不应无来历再现。"""
        result.checks_total += 1
        issues = []

        mentioned = [
            entry for entry in ws.resource_ledger.entries.values()
            if entry.status in ("lost", "consumed", "destroyed") and entry.name in text
        ]

        for entry in mentioned:
            acquire_patterns = [
                rf"获得|得到|拿到|捡到|买入|收到.*{re.escape(entry.name)}",
                rf"{re.escape(entry.name)}.*出现|浮现",
            ]
            acquired = any(re.search(p, text) for p in acquire_patterns)
            if not acquired:
                issues.append(CheckIssue(
                    category="resource",
                    severity="critical",
                    dimension="资源连续性",
                    description=f"资源「{entry.name}」(owner: {entry.owner}) 已 {entry.status}，但本章再次出现",
                    suggestion=f"补充获得「{entry.name}」的情节，或移除相关描写",
                    auto_fixable=True,
                ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 3. 伏笔生命周期 ──
    def _check_foreshadowing_lifecycle(self, text: str, ws: WorldStateLite,
                                       chapter_number: int, result: CodeCheckResult):
        """过期未回收的伏笔告警;已回收伏笔的实体再次出现在伏笔语境中告警。"""
        result.checks_total += 1
        issues = []

        stale = ws.get_stale_foreshadowing(max_age=15, current_chapter=chapter_number)
        for fs in stale:
            age = chapter_number - fs.planted_chapter
            issues.append(CheckIssue(
                category="foreshadowing",
                severity="warning",
                dimension="伏笔生命周期",
                description=f"伏笔「{fs.detail[:30]}...」已埋设 {age} 章仍未回收",
                suggestion="考虑在近期章节中回收此伏笔，或标记为无效",
            ))

        resolved_details = [fs.detail for fs in ws.foreshadowing_pool if fs.status == "resolved"]
        known_names = set(ws.characters.keys()) | {e.name for e in ws.resource_ledger.entries.values()}
        for detail in resolved_details:
            matched_names = [n for n in known_names if n in detail]
            for name in matched_names:
                if name in text:
                    fs_patterns = [
                        rf"{re.escape(name)}[^。！？]{{0,30}}(秘密|真相|隐藏|谜|线索)",
                        rf"(秘密|真相|隐藏|谜|线索)[^。！？]{{0,30}}{re.escape(name)}",
                    ]
                    if any(re.search(p, text) for p in fs_patterns):
                        issues.append(CheckIssue(
                            category="foreshadowing",
                            severity="warning",
                            dimension="伏笔生命周期",
                            description=f"已回收伏笔涉及的实体「{name}」在本章再次出现在伏笔语境中",
                            suggestion="确认是否为新伏笔，避免与已回收伏笔混淆",
                        ))
                        break

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 4. 信息边界 ──
    def _check_information_boundaries(self, text: str, ws: WorldStateLite, result: CodeCheckResult):
        """角色不应知道其不该知道的事;邻近度 200 字符,存证供复核。"""
        result.checks_total += 1
        issues = []

        boundaries = ws.character_matrix.info_boundaries
        if not boundaries:
            result.checks_passed += 1
            return

        fact_knowers: dict[str, set] = {}
        for char_name, boundary in boundaries.items():
            for fact in boundary.known_facts:
                fact_knowers.setdefault(fact, set()).add(char_name)

        for char_name, boundary in boundaries.items():
            if char_name not in text:
                continue

            for fact, knowers in fact_knowers.items():
                if char_name in knowers:
                    continue
                if len(knowers) == 0:
                    continue
                if fact not in text:
                    continue

                char_positions = [m.start() for m in re.finditer(re.escape(char_name), text)]
                fact_positions = [m.start() for m in re.finditer(re.escape(fact), text)]

                for cp in char_positions:
                    for fp in fact_positions:
                        if abs(cp - fp) < 200:
                            ctx_start = min(cp, fp) - 50
                            ctx_end = max(cp + len(char_name), fp + len(fact)) + 50
                            context = text[max(0, ctx_start):min(len(text), ctx_end)]

                            issues.append(CheckIssue(
                                category="information_boundary",
                                severity="warning",
                                dimension="信息边界",
                                description=f"角色「{char_name}」附近出现了其不应知道的信息「{fact[:30]}...」",
                                suggestion=f"确认「{char_name}」是否已通过合理途径获知此信息",
                                evidence=context,
                            ))
                            break
                    else:
                        continue
                    break

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 5. 时间线一致性 ──
    def _check_timeline_consistency(self, text: str, result: CodeCheckResult):
        result.checks_total += 1
        issues = []

        regression_patterns = [
            (r"昨天.*前天", "时间顺序可能倒退"),
            (r"上个月.*这个月.*上周", "时间线交叉"),
        ]
        for pattern, desc in regression_patterns:
            if re.search(pattern, text):
                issues.append(CheckIssue(
                    category="timeline",
                    severity="warning",
                    dimension="时间线一致性",
                    description=f"检测到可能的时间线问题: {desc}",
                    suggestion="检查时间顺序是否合理",
                ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 6. 子情节推进度 ──
    def _check_subplot_stagnation(self, ws: WorldStateLite, chapter_number: int,
                                  result: CodeCheckResult):
        result.checks_total += 1
        issues = []

        stalled = ws.subplot_board.get_stalled(stall_threshold=5, current_chapter=chapter_number)
        for sp in stalled:
            stall_chapters = chapter_number - sp.last_advanced
            issues.append(CheckIssue(
                category="subplot",
                severity="warning",
                dimension="子情节推进度",
                description=f"子情节「{sp.name}」已停滞 {stall_chapters} 章未推进",
                suggestion=f"在近期章节中推进「{sp.name}」，或标记为暂时搁置",
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 7. 对话/叙述比 ──
    def _check_dialogue_ratio(self, text: str, result: CodeCheckResult):
        result.checks_total += 1
        issues = []

        ratio = check_dialogue_ratio(text)
        if ratio < 0.1:
            issues.append(CheckIssue(
                category="style",
                severity="warning",
                dimension="对话/叙述比",
                description=f"对话占比过低 ({ratio:.0%})，可能导致阅读枯燥",
                suggestion="增加角色对话，减少大段叙述",
            ))
        elif ratio > 0.6:
            issues.append(CheckIssue(
                category="style",
                severity="warning",
                dimension="对话/叙述比",
                description=f"对话占比过高 ({ratio:.0%})，可能导致描写不足",
                suggestion="增加场景描写、心理描写和动作描写",
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 8. 字数合规 ──
    def _check_word_count(self, text: str, result: CodeCheckResult):
        result.checks_total += 1
        issues = []

        word_count = len(text)
        lower = int(WORD_COUNT_MIN * (1 - WORD_COUNT_TOLERANCE))
        upper = int(WORD_COUNT_MAX * (1 + WORD_COUNT_TOLERANCE))
        if word_count < lower:
            issues.append(CheckIssue(
                category="word_count",
                severity="warning",
                dimension="字数合规",
                description=f"章节字数过少 ({word_count} 字)，目标 {WORD_COUNT_MIN}-{WORD_COUNT_MAX}",
                suggestion="补充场景描写或对话以达到最低字数",
                auto_fixable=True,
            ))
        elif word_count > upper:
            issues.append(CheckIssue(
                category="word_count",
                severity="warning",
                dimension="字数合规",
                description=f"章节字数过多 ({word_count} 字)，目标 {WORD_COUNT_MIN}-{WORD_COUNT_MAX}",
                suggestion="精简冗余描写，压缩不必要的对话",
                auto_fixable=True,
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1

    # ── 9. anti-AI 扫描 ──
    def _check_anti_ai(self, text: str, result: CodeCheckResult):
        result.checks_total += 1
        issues = []

        fatigue = check_fatigue_words(text)
        for word, count in fatigue:
            issues.append(CheckIssue(
                category="anti_ai",
                severity="warning",
                dimension="疲劳词检测",
                description=f"「{word}」出现 {count} 次，属于高频 AI 用词",
                suggestion=f"替换「{word}」为更具体的描写",
                auto_fixable=True,
            ))

        patterns = check_banned_patterns(text)
        for p in patterns:
            issues.append(CheckIssue(
                category="anti_ai",
                severity="warning",
                dimension="禁用句式检测",
                description=p,
                suggestion="替换为非模板化的表达方式",
                auto_fixable=True,
            ))

        if issues:
            result.issues.extend(issues)
            result.checks_failed += 1
        else:
            result.checks_passed += 1
