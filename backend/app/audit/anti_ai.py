"""去 AI 味检测与规整工具。

移植自 inkflow(inkflow/pipeline/anti_ai.py,MIT License,
Copyright (c) 2026 ElysiaQWQ;详见 THIRD-PARTY-NOTICES.md)。
提供:疲劳词表、禁用句式、教学式改写样例、提示词注入段、后处理检查与破折号清理。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ── 高频 AI 用词(中文) ──
FATIGUE_WORDS = [
    # 高频总结词
    "总之", "综上所述", "总而言之", "不言而喻", "毫无疑问",
    "显而易见", "众所周知", "事实上", "实际上", "坦白说",
    "换言之", "归根结底", "简而言之", "说到底", "话虽如此",
    # 过度修饰
    "宛如", "犹如",
    "不禁", "忍不住", "下意识",
    "情不自禁", "不由自主", "莫名其妙", "鬼使神差",
    # AI 味表达
    "值得一提的是", "需要指出的是", "有趣的是", "令人惊讶的是",
    "不禁让人", "心中暗想", "暗自思忖", "心中一动",
    "若有所思", "恍然大悟", "如梦初醒", "豁然开朗",
    "意味深长", "耐人寻味", "引人深思", "发人深省",
    # 过度使用的情绪词
    "心头一震", "心头一暖", "心头一紧", "心中暗道",
    "暗暗点头", "暗暗心惊", "暗暗赞叹", "暗暗思量",
    "心中一沉", "心中一喜", "心中一酸", "百感交集",
    "五味杂陈", "感慨万千", "心潮澎湃", "热血沸腾",
    # AI 味描述词
    "一缕", "一片", "一阵",
    "淡淡的",
    # AI 味动作标签
    "点了点头", "摇了摇头", "叹了口气", "皱了皱眉",
    "嘴角微微上扬", "眼中闪过一丝", "脸上露出",
    "嘴角勾起一抹", "嘴角的弧度", "目光深邃", "眸光一闪",
    # AI 味过渡词
    "与此同时", "就在这时", "正在此时", "恰在此时",
    "话音刚落", "话音未落", "此言一出", "此话一出",
]

# 自定义疲劳词(运行期可注入,如从设置读取)
_custom_fatigue_words: List[str] = []


def set_custom_fatigue_words(words: List[str]) -> None:
    global _custom_fatigue_words
    _custom_fatigue_words = [w for w in words if w.strip()]


def get_all_fatigue_words(extra_words: List[str] | None = None) -> List[str]:
    return FATIGUE_WORDS + _custom_fatigue_words + (extra_words or [])

# ── 禁用句式(预编译正则) ──
BANNED_PATTERNS = [
    re.compile(r"这(一切|一刻|一瞬).*让.*明白"),
    re.compile(r".*不禁.*感叹.*"),
    re.compile(r".*心中.*暗(暗|道|想).*"),
    re.compile(r"一是.*二是.*三是"),
    re.compile(r"首先.*其次.*最后"),
    re.compile(r"…{2,}"),
    re.compile(r"不是.{1,10}而是"),
    re.compile(r"(.{4,})\1"),
]

# ── 教学式改写样例:关键词 → {diagnosis, original, improved, principle} ──
EXEMPLAR_TEMPLATES: Dict[str, Dict[str, str]] = {
    "总之": {
        "diagnosis": "用「总之」做总结是 AI 写作最常见的收尾方式，显得生硬且缺乏余味。",
        "original": "总之，这一战让他明白了自己的不足。",
        "improved": "他擦掉嘴角的血，盯着对手远去的背影，拳头攥得发白。",
        "principle": "用动作和细节代替总结性陈述。读者能从画面中自行归纳结论，不需要作者替他们说出来。",
    },
    "综上所述": {
        "diagnosis": "「综上所述」是议论文用语，出现在小说中极度违和。",
        "original": "综上所述，这场战争的胜负已经注定。",
        "improved": "帐中无人说话。烛火跳了两下，将军把棋子推倒在地图上。",
        "principle": "小说不是论文。用场景的沉默和角色的动作来传达结论，比直接陈述有力十倍。",
    },
    "不禁": {
        "diagnosis": "「不禁」是 AI 最爱的情绪偷懒词，把复杂感受压缩成一个副词。",
        "original": "她不禁流下了眼泪。",
        "improved": "她别过头去，肩膀抖了一下。等再转回来时，睫毛是湿的。",
        "principle": "情绪要通过可观察的生理反应和微动作传递。「不禁+动词」跳过了所有细节。",
    },
    "仿佛": {
        "diagnosis": "「仿佛」「宛如」「犹如」是 AI 最常用的比喻引导词，过度使用会让比喻变得廉价。",
        "original": "月光洒在地上，仿佛给大地披上了一层银纱。",
        "improved": "月光把他的影子拉得很长，长到能碰到对面的墙。",
        "principle": "好的描写不需要「仿佛」做拐弯。直接写具体的效果和细节，让读者自己感受。",
    },
    "心中暗道": {
        "diagnosis": "「心中暗道」「暗自思忖」「心中暗想」是 AI 内心独白的万能模板。",
        "original": "他心中暗道：这人不简单。",
        "improved": "他后退了半步，手不自觉地按上了刀柄。",
        "principle": "内心活动应该通过外在行为暗示。「后退半步+按刀柄」已经告诉读者他警觉了，不需要内心独白。",
    },
    "若有所思": {
        "diagnosis": "「若有所思」「恍然大悟」「如梦初醒」是 AI 最爱的认知状态标签。",
        "original": "听完这番话，他若有所思地点了点头。",
        "improved": "他没接话，只是用指节敲着桌面，目光落在窗外很远的地方。",
        "principle": "不要给角色贴认知标签。写他的具体反应——敲桌面、望向远方——读者自然知道他在思考。",
    },
    "心头一震": {
        "diagnosis": "「心头一震/一暖/一紧」是 AI 情绪描写的三件套，极度模式化。",
        "original": "听到这个消息，她心头一震。",
        "improved": "她手里的茶杯歪了，茶水淌到桌沿才反应过来。",
        "principle": "情绪冲击要通过失控的身体反应来呈现。「茶杯歪了」比「心头一震」有画面感一百倍。",
    },
    "然而": {
        "diagnosis": "连续使用「然而」「不过」「但是」开头是 AI 最常见的转折依赖症。",
        "original": "然而他并不知道，危险正在逼近。然而命运总是喜欢开玩笑。",
        "improved": "他转身走了。身后的巷子里，有人踩灭了烟头。",
        "principle": "转折不需要用连接词宣告。直接写出对立的画面，让读者自己感受到转折的力量。",
    },
    "值得一提的是": {
        "diagnosis": "「值得一提的是」「需要指出的是」是说明文用语，破坏叙事沉浸感。",
        "original": "值得一提的是，这座桥已经有三百年的历史了。",
        "improved": "桥墩上的石狮子缺了半边脸，据说是乾隆年间那场大水冲的。",
        "principle": "背景信息要融入场景细节，不要用元叙述打断读者的阅读节奏。",
    },
    "竟然": {
        "diagnosis": "「竟然」「居然」是 AI 表达惊讶的万能词，用多了反而不惊讶。",
        "original": "他竟然打败了比自己强三倍的对手。",
        "improved": "对手倒地时，他自己也愣住了。手还在抖，刀上的血还是热的。",
        "principle": "惊讶要通过角色自己的反应来传达。「他自己也愣住了」比「竟然」更有说服力。",
    },
    "——": {
        "diagnosis": "破折号（——）是 AI 最爱的万能标点，用于解释、转折、补充，但高频使用会让文本显得拖沓。",
        "original": "他握紧了拳头——那是他父亲留给他的——眼中闪过一丝决然——他知道，这一战不可避免。",
        "improved": "他握紧拳头，指节发白。父亲的遗物在怀中微微发烫。他抬起头，这一战，不可避免。",
        "principle": "破折号可以用逗号、句号或换行替代。短句比长句+破折号更有力。每章破折号不超过 4 个。",
    },
}

# ── 句式级样例 ──
PATTERN_EXEMPLARS: Dict[str, Dict[str, str]] = {
    r"这(一切|一刻|一瞬).*让.*明白": {
        "diagnosis": "「这一切让他明白」是 AI 最爱的顿悟句式，把成长简化成一句话。",
        "original": "这一切让他明白了，实力才是硬道理。",
        "improved": "他跪在地上，膝盖磕在碎石上，疼得真实。从今天起，他不会再输了。",
        "principle": "成长和顿悟要通过角色的行动变化来体现，而不是一句总结。",
    },
    r"一是.*二是.*三是": {
        "diagnosis": "「一是…二是…三是…」是议论文排比，小说里用这个就像在写报告。",
        "original": "他有三个优势：一是速度快，二是力量大，三是经验丰富。",
        "improved": "他快得像阵风，拳头砸下来能把石板砸裂，更别提身上那十七道疤——每一道都是一场生死。",
        "principle": "用具体场景和细节展示优势，不要用编号列表。小说不是PPT。",
    },
    r"不是.{1,10}而是": {
        "diagnosis": "「不是A而是B」是 AI 最爱的对比句式，显得生硬且模式化。",
        "original": "他不是害怕，而是兴奋。这不是退缩，而是蓄力。",
        "improved": "他的手在抖，嘴角却在上扬。他后退一步，蹲得更低，像一头即将扑出的豹子。",
        "principle": "对比不需要用「不是…而是」宣告。直接写出矛盾的行为和细节，读者自己会感受到张力。",
    },
}


def find_fatigue_context(text: str, word: str, context_chars: int = 40) -> List[str]:
    """找疲劳词出现位置及上下文片段。"""
    contexts = []
    start = 0
    while True:
        idx = text.find(word, start)
        if idx == -1:
            break
        ctx_start = max(0, idx - context_chars)
        ctx_end = min(len(text), idx + len(word) + context_chars)
        snippet = text[ctx_start:ctx_end]
        if ctx_start > 0:
            snippet = "…" + snippet
        if ctx_end < len(text):
            snippet = snippet + "…"
        contexts.append(snippet)
        start = idx + len(word)
    return contexts


def generate_learning_examples(analysis: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
    """为每个检出问题生成教学样例(诊断/原文/改句/原则)。"""
    examples = []

    for word, count in analysis.get("fatigue_words", []):
        template = EXEMPLAR_TEMPLATES.get(word)
        if template:
            examples.append({
                "type": "fatigue_word",
                "keyword": word,
                "count": count,
                "contexts": find_fatigue_context(text, word),
                "diagnosis": template["diagnosis"],
                "original": template["original"],
                "improved": template["improved"],
                "principle": template["principle"],
            })

    for pattern_desc in analysis.get("banned_patterns", []):
        match = re.search(r"Pattern '(.+?)' matched", pattern_desc)
        if not match:
            continue
        pattern = match.group(1)
        template = PATTERN_EXEMPLARS.get(pattern)
        if template:
            actual_matches = re.findall(pattern, text)
            examples.append({
                "type": "banned_pattern",
                "pattern": pattern,
                "count": len(actual_matches),
                "contexts": [m if isinstance(m, str) else str(m) for m in actual_matches[:3]],
                "diagnosis": template["diagnosis"],
                "original": template["original"],
                "improved": template["improved"],
                "principle": template["principle"],
            })

    return examples


def build_anti_ai_prompt_section() -> str:
    """生成写作约束(去 AI 味)提示词段。"""
    fatigue_sample = "、".join(FATIGUE_WORDS[:20])
    return f"""
## 写作约束（去 AI 味）

### 禁用词汇（避免使用以下过度使用的词）：
{fatigue_sample}，以及类似的陈词滥调。

### 禁用句式：
- 不要用"一是…二是…三是…"的排比
- 不要用"总之/综上所述"做总结
- 不要用"不禁/忍不住"开头的情绪句
- 不要用"心中暗想/暗自思忖"这类内心独白套话
- 不要用重复的句式开头（连续两段以"然而"开头）
- 不要用"不是…而是…"的对比句式
- 破折号（——）每章最多 4 个，优先用逗号、句号或换行替代

### 要求：
- 对话要口语化，符合角色身份
- 描写要用具体的感官细节，不要用抽象形容
- 句式要有长短变化，避免全是 15-20 字的中等句
- 每段对话后不要都跟"他说道"、"她回应道"
- 情绪表达要通过动作和细节传递，不要直接说"他感到悲伤"
"""


def check_fatigue_words(text: str, extra_words: List[str] | None = None) -> List[Tuple[str, int]]:
    """检查高频 AI 用词,返回 (词, 次数) 列表,出现 3 次以上计入。"""
    issues = []
    for word in get_all_fatigue_words(extra_words):
        count = text.count(word)
        if count >= 3:
            issues.append((word, count))
    return sorted(issues, key=lambda x: x[1], reverse=True)


def check_banned_patterns(text: str) -> List[str]:
    """检查禁用句式,返回命中的模式描述。"""
    issues = []
    for pattern in BANNED_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            issues.append(f"Pattern '{pattern.pattern}' matched {len(matches)} times")
    return issues


def check_sentence_variety(text: str) -> Dict[str, float]:
    """句长分布分析:平均句长/短句占比/长句占比/多样性分。"""
    sentences = re.split(r"[。！？\n]", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return {"avg_length": 0, "short_ratio": 0, "long_ratio": 0, "variety_score": 0}

    lengths = [len(s) for s in sentences]
    avg = sum(lengths) / len(lengths)
    short = sum(1 for l in lengths if l < 10) / len(lengths)
    long_ = sum(1 for l in lengths if l > 30) / len(lengths)

    if len(lengths) > 1:
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        variety = variance ** 0.5
    else:
        variety = 0

    return {
        "avg_length": round(avg, 1),
        "short_ratio": round(short, 2),
        "long_ratio": round(long_, 2),
        "variety_score": round(variety, 1),
    }


def check_dash_count(text: str) -> int:
    """统计破折号(——)出现次数。"""
    return text.count("——")


def check_dialogue_ratio(text: str) -> float:
    """计算对话字符占总字符比(0-1)。"""
    dialogue_chars = 0
    in_dialogue = False
    for ch in text:
        if ch in ('"', "“", "”", "「", "」", "『", "』", "“", "”"):
            in_dialogue = not in_dialogue
        elif in_dialogue:
            dialogue_chars += 1

    total = len(text) if text else 1
    return round(dialogue_chars / total, 2)


def analyze_text(text: str, extra_words: List[str] | None = None) -> Dict:
    """完整 anti-AI 分析:疲劳词/禁用句式/句式统计/对话比/破折号/评分(100 满分)。"""
    fatigue = check_fatigue_words(text, extra_words)
    patterns = check_banned_patterns(text)
    sentence_stats = check_sentence_variety(text)
    dialogue_ratio = check_dialogue_ratio(text)
    dash_count = check_dash_count(text)

    score = 100
    score -= len(fatigue) * 3
    score -= len(patterns) * 10
    if sentence_stats["variety_score"] < 5:
        score -= 15
    if dialogue_ratio < 0.1:
        score -= 10
    if dialogue_ratio > 0.6:
        score -= 10
    if dash_count > 4:
        score -= (dash_count - 4) * 3

    return {
        "fatigue_words": fatigue,
        "banned_patterns": patterns,
        "sentence_stats": sentence_stats,
        "dialogue_ratio": dialogue_ratio,
        "dash_count": dash_count,
        "score": max(0, min(100, score)),
    }


def cleanup_dashes(text: str, max_dashes: int = 4) -> str:
    """清理超额破折号:保留前 max_dashes 个,其余替换为逗号。"""
    parts = text.split("——")

    if len(parts) <= max_dashes + 1:
        return text

    result_parts = [parts[0]]
    dash_count = 0

    for i in range(1, len(parts)):
        if dash_count < max_dashes:
            result_parts.append("——" + parts[i])
            dash_count += 1
        else:
            prev_char = parts[i - 1][-1] if parts[i - 1] else ""
            connector = "" if prev_char in "，。！？、" else "，"
            result_parts.append(connector + parts[i])

    return "".join(result_parts)
