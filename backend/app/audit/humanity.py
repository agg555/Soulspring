"""去 AI 味质量信号(零 token 确定性检测)。

移植自 chevoink(启创墨域)commit b301168 的 `api/lib/agent/humanity-quality.ts`
`analyzeDeterministicQuality`,按移植当时(2026-08-31)的 MIT License 取得,
Copyright (c) 2026 Xcy8010;上游其后将许可改为 AGPL-3.0。本文件随本项目整体
以 AGPL-3.0 发布(来源区分与许可历史见 THIRD-PARTY-NOTICES.md)。
算法与阈值随原作,接口改为对齐 Soulspring 的审计结构。

与 anti_ai.py 的分工(重要,别混用):
- anti_ai 是**全局词表/句式黑名单**,常驻注入并逐条计数;
- 本模块按 chevoink 23 号方案 §9.1「不做全局禁词」的思路,只报**带原文证据的局部异常**,
  不做题材一刀切。故本模块的 severity 最高只到 warning,绝不产出 critical
  ——审美信号不能被硬阈值直接阻断(原文 §9.3)。

原作判据公式:
    异常风险 = 题材不匹配 × 局部频率异常 × 缺少语义铺垫 × 未服务人物/情节 × 近期重复
其中"题材不匹配""缺少语义铺垫"需要 LLM 判断,留给评审环节;
本模块只做可确定性定位的部分(频率、结构、重复、符号误用)。

五类确定性信号:
    style_drift        相邻段落句长中位数突变
    explanation_echo   动作/对白后被叙述重复解释
    sentence_homology  连续三句同构(同起句或近似长度+同停顿)
    image_repetition   意象在本章或近期章节机械复用
    punctuation_misuse 「」被当圈重点符号包裹叙述而非人物话语
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 句读切分:与中文标点习惯对齐,省略号与换行也视为断句
_SENT_RE = re.compile(r"[^。！？!?…\n]+(?:[。！？!?…]+|$)")
# 意象句:比喻词开头,到第一个句读为止
_IMAGE_RE = re.compile(r"(像|仿佛|如同|好似)[^，。！？!?\n]{2,28}")
# 「」包裹的长片段:18-360 字,短于 18 字多为正常对话
_CORNER_RE = re.compile(r"「([^」\n]{18,360})」")
# 叙述线索:出现这些,基本可判定「」里装的是叙述而非人物话语
_NARRATION_CUE_RE = re.compile(
    r"[（）()]|(?:镜头|画面|转场|那段|过程|一路|拐进|挤着|穿过|进入|走到|来到|门内|屋里)"
)
_PUNCT_RE = re.compile(r"[\s，。！？!?、：“”‘’（）()—…]")

# 阈值随原作,改动需在文档注明理由
STYLE_DRIFT_RATIO = 2.8
STYLE_DRIFT_MIN_CUR = 70
STYLE_DRIFT_MIN_PREV = 40
ECHO_JACCARD = 0.58
ECHO_MIN_CHARS = 12
HOMOLOGY_MIN_OPENING = 3
MAX_FINDINGS = 20

# 信号中文名(展示用,与 chevoink 工具层 label 保持一致)
SIGNAL_LABELS = {
    "style_drift": "文风漂移",
    "explanation_echo": "解释回声",
    "sentence_homology": "句式同构",
    "image_repetition": "意象重复",
    "punctuation_misuse": "引号误用",
}


@dataclass
class Span:
    """带原文位置的片段。"""
    text: str
    start: int
    end: int


@dataclass
class HumanityFinding:
    signal: str                 # 见 SIGNAL_LABELS
    severity: str               # warning|info(对应原作 warning|advisory)
    confidence: float
    description: str
    suggestion: str
    evidence: str
    start: int = 0
    end: int = 0

    def to_dict(self) -> dict:
        return {
            "signal": self.signal, "label": SIGNAL_LABELS.get(self.signal, self.signal),
            "severity": self.severity, "confidence": round(self.confidence, 3),
            "description": self.description, "suggestion": self.suggestion,
            "evidence": self.evidence, "start": self.start, "end": self.end,
        }


@dataclass
class HumanityResult:
    findings: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def to_dict(self) -> dict:
        return {
            "metrics": self.metrics,
            "signals": sorted({f.signal for f in self.findings}),
            "findings": [f.to_dict() for f in self.findings],
        }


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def split_paragraphs(content: str) -> list[Span]:
    out, pos = [], 0
    for raw in content.split("\n"):
        text = raw.strip()
        if text:
            start = content.index(text, pos)
            out.append(Span(text, start, start + len(text)))
            pos = start + len(text)
    return out


def split_sentences(content: str) -> list[Span]:
    out = []
    for m in _SENT_RE.finditer(content):
        raw = m.group(0)
        lead = len(raw) - len(raw.lstrip())
        text = raw.strip()
        if len(text) < 2:
            continue
        start = m.start() + lead
        out.append(Span(text, start, start + len(text)))
    return out


def chinese_bigrams(value: str) -> set[str]:
    compact = _PUNCT_RE.sub("", value)
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    inter = len(left & right)
    return inter / (len(left) + len(right) - inter)


def _evidence(content: str, start: int, end: int) -> str:
    return content[start:min(end, start + 360)]


def analyze_deterministic_quality(
    content: str, recent_chapter_texts: list[str] | None = None
) -> HumanityResult:
    """零 token 检测去 AI 味质量信号。

    recent_chapter_texts:近期章节正文,用于跨章意象重复检测(对应 L2 回写的沉淀)。
    """
    paragraphs = split_paragraphs(content)
    sentences = split_sentences(content)
    lengths = [len(s.text.replace(" ", "")) for s in sentences]
    findings: list[HumanityFinding] = []

    # 对话占比:整段以引号开头或结尾的按对话计
    dialogue_chars = sum(
        len(p.text) for p in paragraphs
        if re.match(r'^[“「『"]', p.text) or re.search(r'[”」』"]\s*$', p.text)
    )

    # 1) style_drift:相邻段落句长中位数突变
    for i in range(1, len(paragraphs)):
        prev = [len(s.text) for s in split_sentences(paragraphs[i - 1].text)]
        cur = [len(s.text) for s in split_sentences(paragraphs[i].text)]
        pm, cm = median(prev), median(cur)
        ratio = max(pm, cm) / max(1.0, min(pm, cm))
        if (ratio >= STYLE_DRIFT_RATIO
                and len(paragraphs[i].text) >= STYLE_DRIFT_MIN_CUR
                and len(paragraphs[i - 1].text) >= STYLE_DRIFT_MIN_PREV):
            findings.append(HumanityFinding(
                signal="style_drift", severity="info", confidence=0.72,
                description=f"相邻段落句长中位数从 {round(pm)} 变为 {round(cm)},变化 {ratio:.1f} 倍;"
                            f"这里只提示漂移,不判定长句或短句本身错误。",
                suggestion="核对该变化是否来自视角、场景节奏或作者有意处理;若不是,只调整这一段的句群节奏。",
                evidence=_evidence(content, paragraphs[i].start, paragraphs[i].end),
                start=paragraphs[i].start, end=paragraphs[i].end,
            ))

    # 2) explanation_echo:相邻句词组高度重合(动作/对白后被重复解释)
    for i in range(1, len(sentences)):
        sim = jaccard(chinese_bigrams(sentences[i - 1].text), chinese_bigrams(sentences[i].text))
        if sim >= ECHO_JACCARD and min(len(sentences[i - 1].text), len(sentences[i].text)) >= ECHO_MIN_CHARS:
            findings.append(HumanityFinding(
                signal="explanation_echo", severity="warning", confidence=min(0.95, sim),
                description=f"本句与前句词组重合度 {sim:.2f},可能在动作或对白后再次解释同一信息。",
                suggestion="优先删除重复解释;若承担新信息,只保留新增部分。",
                evidence=_evidence(content, sentences[i].start, sentences[i].end),
                start=sentences[i].start, end=sentences[i].end,
            ))

    # 3) sentence_homology:连续三句同起句,或长度近似且都带逗号停顿
    for i in range(len(sentences) - 2):
        group = sentences[i:i + 3]
        openings = [re.sub(r'^[“「『"\'‘’\s]+', "", s.text)[:HOMOLOGY_MIN_OPENING] for s in group]
        lens = [len(s.text) for s in group]
        close_lengths = (max(lens) - min(lens)) <= max(5, median(lens) * 0.18)
        same_opening = bool(openings[0]) and all(o == openings[0] for o in openings)
        if same_opening or (close_lengths and all("，" in s.text or "," in s.text for s in group)):
            findings.append(HumanityFinding(
                signal="sentence_homology", severity="info", confidence=0.68,
                description="连续三句具有相同起句或近似长度与停顿结构,可能形成机械排比;有意排比则可保留。",
                suggestion="仅在非刻意修辞时打散其中一句的观察角度或信息落点,不做同义词轮换。",
                evidence=_evidence(content, group[0].start, group[2].end),
                start=group[0].start, end=group[2].end,
            ))

    # 4) image_repetition:意象在本章重复,或在近期章节已用过
    reference = "\n".join(recent_chapter_texts or [])
    seen: dict[str, int] = {}
    for m in _IMAGE_RE.finditer(content):
        normalized = m.group(0).replace(" ", "")
        prior = seen.get(normalized, 0)
        repeated_recently = normalized in reference
        if prior > 0 or repeated_recently:
            findings.append(HumanityFinding(
                signal="image_repetition", severity="info",
                confidence=0.78 if repeated_recently else 0.70,
                description="这个完整意象在近期章节已经出现。" if repeated_recently
                            else "这个完整意象在本章重复出现。",
                suggestion="若不是主题回声,保留最有效的一处,其余改为人物动作、物件变化或直接叙述。",
                evidence=_evidence(content, m.start(), m.start() + len(m.group(0))),
                start=m.start(), end=m.start() + len(m.group(0)),
            ))
        seen[normalized] = prior + 1

    # 5) punctuation_misuse:「」整体包裹叙述/转场/画面,而非人物话语
    for m in _CORNER_RE.finditer(content):
        inner = m.group(1)
        if not _NARRATION_CUE_RE.search(inner):
            continue
        findings.append(HumanityFinding(
            signal="punctuation_misuse", severity="warning", confidence=0.9,
            description="这段包含转场、画面或动作过程,却被「」整体包裹;「」不能作为叙述段落的视觉强调符号。",
            suggestion="保留原叙述内容,只移除误用的「」;人物直接说出或逐字引用的内容不改。",
            evidence=_evidence(content, m.start(), m.start() + len(m.group(0))),
            start=m.start(), end=m.start() + len(m.group(0)),
        ))

    # 同信号同位置去重,并按位置排序后截断
    deduped: list[HumanityFinding] = []
    for f in sorted(findings, key=lambda x: (x.start, x.signal)):
        if any(d.signal == f.signal and d.start == f.start and d.end == f.end for d in deduped):
            continue
        deduped.append(f)
    deduped = deduped[:MAX_FINDINGS]

    metrics = {
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "median_sentence_chars": round(median(lengths), 1) if lengths else 0,
        "max_sentence_chars": max(lengths) if lengths else 0,
        "dialogue_ratio": round(dialogue_chars / len(content), 3) if content else 0,
        "signal_count": len(deduped),
        "signals": sorted({f.signal for f in deduped}),
    }
    return HumanityResult(findings=deduped, metrics=metrics)
