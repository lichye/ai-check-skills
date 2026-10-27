#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI-check: deterministic text scanner and AI-score report generator for any material.

This script deliberately does not call any AI model and does not calculate final
AI-writing probabilities. It extracts text from DOCX, LaTeX, Markdown, PDF, HTML or plain text, builds chunks, scans
explainable trace features, and renders reports from assistant-provided results.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal


SectionType = Literal[
    "abstract",
    "keywords",
    "chapter_title",
    "body",
    "conclusion",
    "references",
    "other",
]
Importance = Literal["high", "medium", "low"]
Sensitivity = Literal["high", "medium", "low"]
Verdict = Literal["ai", "human", "suspicious"]


MAX_CHARS_PER_CHUNK = 900
# Paragraphs shorter than this are merged with short neighbours; longer ones are judged on their own,
# so a concrete paragraph never inherits the score of a generic one next to it.
MERGE_BELOW_CHARS = 200
REPORT_MIN_VALUE = 0.30
# Risk bands. Anything flagged (>= REPORT_MIN_VALUE) already reads as AI-written and needs a rewrite.
HIGH_RISK_VALUE = 0.60


def risk_band(value: float) -> str:
    return "high" if value >= HIGH_RISK_VALUE else "medium" if value >= REPORT_MIN_VALUE else "low"
REPORT_FRAGMENT_MAX_CHARS = 360
REPORT_FRAGMENT_MIN_CHARS = 24
DETECTION_SCOPE = (
    "Text generated or polished by large language models, including ChatGPT/GPT, Claude, Gemini, "
    "DeepSeek, Qwen, Doubao, Kimi, GLM, ERNIE, Hunyuan, MiniMax, Spark and Grok"
)


TEMPLATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("firstly/secondly/finally sequence (zh)", re.compile(r"首先[\s\S]{0,120}其次[\s\S]{0,120}(?:最后|最终)")),
    ("numbered first/second/third list (zh)", re.compile(r"一是[\s\S]{0,120}二是[\s\S]{0,120}三是")),
    ("stacked additive connectors (zh)", re.compile(r"此外[\s\S]{0,120}同时[\s\S]{0,120}另外")),
    ("on-the-one-hand symmetry (zh)", re.compile(r"一方面[\s\S]{0,120}另一方面")),
    ("not-only/but-also symmetry (zh)", re.compile(r"不仅[\s\S]{0,120}(?:而且|更|还|也)")),
    ("in-summary closer (zh)", re.compile(r"综上所述")),
    ("all-in-all closer (zh)", re.compile(r"总而言之|总的来说|综合来看|简而言之")),
    ("it-follows-that closer (zh)", re.compile(r"由此可见")),
    ("it-is-worth-noting filler (zh)", re.compile(r"值得(?:注意|一提|关注)的是|需要指出的是|不难发现")),
    ("undeniably filler (zh)", re.compile(r"不可否认")),
    ("beyond-doubt filler (zh)", re.compile(r"毋庸置疑")),
    ("obviously filler (zh)", re.compile(r"显而易见")),
    ("as-is-well-known filler (zh)", re.compile(r"众所周知")),
    ("goes-without-saying filler (zh)", re.compile(r"不言而喻")),
    ("with-the-rapid-development-of opener (zh)", re.compile(r"随着.{0,24}?的?(?:快速|飞速|迅猛|迅速|不断|持续|蓬勃)发展")),
    ("against-the-backdrop-of opener (zh)", re.compile(r"在.{0,20}?(?:大背景|背景|浪潮|时代)下")),
    # English prose
    ("In conclusion/summary", re.compile(r"\b(?:in conclusion|in summary|to sum up|all in all)\b", re.I)),
    ("It is worth noting", re.compile(r"\bit is (?:worth noting|important to note|noteworthy) that\b", re.I)),
    ("not only…but also", re.compile(r"\bnot only\b[\s\S]{0,120}\bbut also\b", re.I)),
    ("Firstly/Secondly/Finally", re.compile(r"\bfirst(?:ly)?,[\s\S]{0,240}\bsecond(?:ly)?,[\s\S]{0,240}\b(?:finally|lastly|third(?:ly)?),", re.I)),
    ("In today's… opener", re.compile(r"\bin (?:today's|the modern|an era of|the rapidly evolving|the ever-evolving)\b", re.I)),
]

CONNECTORS = (
    "因此",
    "然而",
    "同时",
    "此外",
    "另外",
    "由此可见",
    "综上",
    "进一步",
    "相较之下",
    "具体而言",
    "首先",
    "其次",
    "最后",
    "一方面",
    "另一方面",
)

EN_CONNECTOR_RE = re.compile(
    r"\b(?:moreover|furthermore|additionally|in addition|however|therefore|consequently|thus|hence|"
    r"nevertheless|notably|importantly|overall|specifically)\b",
    re.I,
)

GENERIC_CLAIM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("great-significance claim (zh)", re.compile(r"(?:具有|具备).{0,12}(?:重要|重大).{0,12}(?:意义|价值)")),
    ("broad-prospects claim (zh)", re.compile(r"(?:广阔|良好).{0,8}(?:应用)?前景|前景(?:十分|非常)?广阔")),
    ("theoretical-and-practical-value claim (zh)", re.compile(r"理论价值.{0,12}现实意义|现实意义.{0,12}理论价值")),
    ("efficient-reliable-system goal (zh)", re.compile(r"(?:高效|可靠|可信|智能化|实用化).{0,18}(?:系统|框架|方案)")),
    ("in-depth-study claim (zh)", re.compile(r"(?:深入|全面).{0,8}研究")),
    ("series-of-challenges claim (zh)", re.compile(r"一系列.{0,8}(?:问题|挑战)")),
    ("empower/boost buzzwords (zh)", re.compile(r"赋能|助力|深度融合|全方位|多维度|新范式|新路径|新思路")),
    ("plays-a-key-role claim (zh)", re.compile(r"发挥(?:着)?.{0,6}(?:重要|关键|不可替代|积极)(?:的)?作用|至关重要|举足轻重")),
    ("solid-foundation claim (zh)", re.compile(r"(?:提供|奠定)(?:了)?.{0,6}(?:有力|坚实|重要)(?:的)?(?:支撑|基础|保障)")),
    ("increasingly-prominent claim (zh)", re.compile(r"日益(?:增长|突出|凸显|重要|广泛|迫切)|愈发(?:重要|突出)")),
    # English LLM-flavoured vocabulary; each hit is weak evidence only
    (
        "LLM-favoured vocabulary",
        re.compile(
            r"\b(?:delve[sd]?|delving|tapestry|testament to|pivotal|underscor(?:e|es|ed|ing)|showcas(?:e|es|ed|ing)|"
            r"intricate|multifaceted|realm|seamless(?:ly)?|cutting-edge|ever-evolving|paving the way|"
            r"shed(?:s|ding)? light on|navigat(?:e|es|ing) the complexities|game[- ]changer)\b",
            re.I,
        ),
    ),
    ("crucial role", re.compile(r"\bplay(?:s|ing)? an? (?:crucial|pivotal|vital|key|significant|important) role\b", re.I)),
    ("significant implications", re.compile(r"\b(?:significant|profound|far-reaching) (?:implications|potential)\b|\bbroad (?:application )?prospects\b", re.I)),
]

# Over-defense: writing that argues against an imagined objection. One precise boundary is evidence;
# several guards, contrasts and disclaimers per sentence are an AI-writing habit.
DEFENSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "negation contrast",
        re.compile(
            r"\b(?:rather than|instead of|as opposed to|and not|but not)\b|\bnot\s+(?:\w+\s+){0,6}?\w+,?\s+but\b"
            r"|而(?:不是|非)|不是[^。！？]{0,30}而是|并非[^。！？]{0,30}而是",
            re.I,
        ),
    ),
    (
        "guard clause",
        re.compile(
            r"\b(?:only (?:when|if)|if and only if|provided that|as long as|subject to|unless)\b"
            r"|\bunder (?:the |its |their )?(?:[\w-]+ ){0,2}(?:assumptions?|conditions?|constraints?)\b"
            r"|仅当|只有[^。！？]{0,30}才|当且仅当|前提是|在[^。！？]{0,20}(?:假设|前提|条件)下",
            re.I,
        ),
    ),
    (
        "disclaimer",
        re.compile(
            r"\b(?:we do not claim|we make no claim|this (?:is not to say|does not (?:mean|imply))|is not intended to"
            r"|it should be noted|note that|we (?:stress|emphasi[sz]e) that|to be clear|importantly,|crucially,)"
            r"|需要(?:指出|强调)|值得强调|并不意味着|并不声称",
            re.I,
        ),
    ),
    (
        "hedge",
        re.compile(
            r"\b(?:may|might|potentially|possibly|arguably|to some extent|to the extent that|in principle"
            r"|aims? to|is intended to|tends? to|largely|relatively)\b|可能|或许|在一定程度上|旨在|相对而言",
            re.I,
        ),
    ),
]
# Qualifiers that pin a detail down again ("the original property on the full RTL under the original
# assumptions"); three or more on one sentence is unbounded defence of a detail.
DETAIL_QUALIFIER_RE = re.compile(
    r"\b(?:the|its|their|each|every|all) (?:original|full|entire|whole|supplied|global|same|complete|exact|underlying)\b"
    r"|原始|完整的|全部的|同一",
    re.I,
)
# Four-word guard phrases: preposition + determiner + two words ("under the original assumptions").
GUARD_PHRASE_RE = re.compile(r"\b(?:under|against|within|on|subject to) (?:the|its|their) [\w'-]+ [\w'-]+\b", re.I)

METHOD_NAME_RE = re.compile(
    r"\b(?:CNN|RNN|LSTM|GRU|Transformer|BERT|GPT-?\d*|ResNet-?\d*|U-?Net|YOLO\w*|ViT|Grad-CAM|XGBoost|SVM|CQT|MFCC|"
    r"BSCQT|DCAM|DCAMNet|AB-CQT|DFAM|DFAMNet)\b"
    # generic CamelCase / acronym model names with >=3 chars, e.g. BiLSTM, EfficientNet-B0, LoRA
    r"|\b(?=[A-Za-z0-9-]{3,}\b)[A-Z][A-Za-z]*[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)?\b"
)

EVIDENCE_MARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("citation markers", re.compile(r"\[\d+(?:\s*[-–,，、]\s*\d+)*\]|\([A-Z][A-Za-z-]+(?: et al\.)?,? \d{4}[a-z]?\)")),
    (
        "metrics",
        re.compile(
            r"\d+(?:\.\d+)?\s*(?:%|％|G\s*FLOPs?|FLOPs?|MB|GB|ms|s|Hz|kHz|MHz|dB|mAP|AUC|F1|BLEU|ROUGE|mIoU|PSNR|SSIM)(?![A-Za-z])",
            re.I,
        ),
    ),
    ("statistics", re.compile(r"\bp\s*[<=>≤]\s*0?\.\d+|±|95\s*%\s*CI|\bn\s*=\s*\d+|标准差|置信区间")),
    ("named methods or models", METHOD_NAME_RE),
    (
        "experiment or result wording",
        re.compile(r"实验结果(?:表明|显示|验证)|准确率|召回率|计算复杂度|消融|对比实验|数据集|\b(?:ablation|baseline|dataset|benchmark)s?\b", re.I),
    ),
    (
        "scope or trade-off",
        re.compile(
            r"在.{0,18}(?:条件|场景|约束|限制)下|针对.{0,24}(?:问题|场景|任务)|本文(?:聚焦|采用|选取|限定)"
            r"|\b(?:under the (?:condition|assumption)|limited to|we (?:restrict|focus on|chose|choose|adopt))\b",
            re.I,
        ),
    ),
]


@dataclass
class TraceFeatures:
    riskSignals: list[str]
    mitigatingSignals: list[str]
    templatePhrases: list[str]
    connectorCount: int
    connectorDensity: float
    sentenceCount: int
    sentenceLengthVariance: float | None
    sentenceLengthCV: float | None
    uniformSentenceRhythm: bool
    genericClaimCount: int
    evidenceMarkers: list[str]
    defenseMarkers: list[str]
    defenseCount: int


@dataclass
class Chunk:
    chunkId: str
    sectionType: SectionType
    sectionTitle: str | None
    text: str
    charCount: int
    importance: Importance
    traceFeatures: TraceFeatures


@dataclass
class Result:
    chunkId: str
    sensitivity: Sensitivity
    aiScore: float
    verdict: Verdict
    reason: str
    signals: list[str]


def unique_limited(values: Iterable[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def normalize_paragraphs(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in re.split(r"\n+", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
        if re.sub(r"\s+", " ", line).strip()
    ]


SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|(?<=[.])\s+(?=[A-Z0-9\"“(\[])")


def join_sentences(left: str, right: str) -> str:
    """Re-join split sentences: CJK needs no separator, Latin text needs the space back."""
    if not left:
        return right
    if re.search(r"[A-Za-z0-9.,;:!?)\]\"”]$", left) and re.match(r"[A-Za-z0-9\"“(\[]", right):
        return f"{left} {right}"
    return f"{left}{right}"


def split_sentences(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", item).strip()
        for item in SENTENCE_SPLIT_RE.split(text or "")
        if count_chars(item) > 5
    ]


def pattern_count(text: str, pattern: re.Pattern[str]) -> int:
    return len(pattern.findall(text or ""))


def scan_trace_features(text: str) -> TraceFeatures:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    sentences = split_sentences(normalized)
    sentence_lengths = [count_chars(sentence) for sentence in sentences]
    variance: float | None = None
    cv: float | None = None
    if sentence_lengths:
        avg = sum(sentence_lengths) / len(sentence_lengths)
        variance = sum((length - avg) ** 2 for length in sentence_lengths) / len(sentence_lengths)
        cv = math.sqrt(variance) / avg if avg else None
    # Coefficient of variation instead of raw variance so the same rule works for Chinese
    # (short sentences) and English (long sentences counted in letters).
    uniform = len(sentences) >= 4 and cv is not None and cv < 0.3

    template_phrases = unique_limited(label for label, pattern in TEMPLATE_PATTERNS if pattern.search(normalized))
    connector_count = sum(normalized.count(connector) for connector in CONNECTORS) + pattern_count(normalized, EN_CONNECTOR_RE)
    connector_density = round(connector_count / len(sentences), 3) if sentences else 0.0
    # Chinese "——" pairs and English em dashes used as clause glue.
    dash_count = normalized.count("——") + len(re.findall(r"(?<!—)—(?!—)", normalized))

    generic_labels: list[str] = []
    generic_count = 0
    for label, pattern in GENERIC_CLAIM_PATTERNS:
        count = pattern_count(normalized, pattern)
        if count:
            generic_count += count
            generic_labels.append(label)

    evidence_markers = unique_limited(
        label for label, pattern in EVIDENCE_MARKER_PATTERNS if pattern.search(normalized)
    )
    method_names = {match.group(0) for match in METHOD_NAME_RE.finditer(normalized)}

    defense_counts = {label: pattern_count(normalized, pattern) for label, pattern in DEFENSE_PATTERNS}
    # Hedges are common in honest prose; they count toward over-defense only from the second one on.
    defense_count = sum(count for label, count in defense_counts.items() if label != "hedge") + max(0, defense_counts["hedge"] - 1)
    stacked = sum(1 for sentence in sentences if pattern_count(sentence, DETAIL_QUALIFIER_RE) >= 3)
    if stacked:
        defense_counts["stacked qualifiers"] = stacked
        defense_count += 2 * stacked
    defense_markers = [label for label, count in defense_counts.items() if count]
    over_defense = bool(sentences) and defense_count >= 2 and defense_count / len(sentences) >= 0.5

    openers = [" ".join(re.findall(r"[A-Za-z']+", sentence)[:2]).lower() for sentence in sentences]
    openers = [opener for opener in openers if opener]
    top_opener = max(set(openers), key=openers.count) if openers else ""
    repeated_opener = len(sentences) >= 3 and openers.count(top_opener) >= 2 and openers.count(top_opener) / len(sentences) >= 0.5

    risk_signals = [
        *(f"template phrase: {label}" for label in template_phrases),
        "uniform sentence rhythm" if uniform else "",
        "dense connectors" if connector_density >= 0.45 and connector_count >= 3 else "",
        "stacked dashes" if dash_count >= 2 else "",
        f"generic claims: {' / '.join(unique_limited(generic_labels, 3))}" if generic_count else "",
        "contribution-list structure"
        if re.search(
            r"主要研究工作如下|具体研究内容如下|本文(?:提出|构建|设计).{0,80}(?:方法|框架).{0,80}(?:实验结果|结果表明)"
            r"|\b(?:our|the main) contributions (?:are|of this (?:paper|work))\b",
            normalized,
            re.I,
        )
        else "",
        f"over-defense: {' / '.join(defense_markers)}" if over_defense else "",
        f"repeated sentence opener: '{top_opener}'" if repeated_opener else "",
        "generic goal statement" if re.search(r"(?:旨在|力求|致力于).{0,40}(?:高效|可靠|可信|智能化|实用化)", normalized) else "",
    ]

    mitigating = [
        *(f"concrete evidence: {label}" for label in evidence_markers),
        "domain method detail" if len(method_names) >= 2 else "",
        "quantified results"
        if re.search(r"\d+(?:\.\d+)?\s*[%％]", normalized)
        and re.search(r"准确率|提升|降低|复杂度|FLOPs?|\b(?:improv|reduc|outperform|accuracy)", normalized, re.I)
        else "",
        "stated limitations"
        if re.search(r"(?:但|然而|不过).{0,40}(?:限制|不足|难以|约束|挑战)", normalized)
        or re.search(r"\b(?:however|but|although)\b.{0,80}\b(?:limit(?:ation|ed|s)?|cannot|fails?|constraints?|drawbacks?)\b", normalized, re.I)
        else "",
    ]

    if over_defense:
        # Boundaries buried in a stack of guards are part of the problem, not evidence against it.
        mitigating = [item for item in mitigating if not item.startswith(("concrete evidence: scope", "stated limitations"))]

    return TraceFeatures(
        riskSignals=unique_limited(risk_signals),
        mitigatingSignals=unique_limited(mitigating),
        templatePhrases=template_phrases,
        connectorCount=connector_count,
        connectorDensity=connector_density,
        sentenceCount=len(sentences),
        sentenceLengthVariance=round(variance, 3) if variance is not None else None,
        sentenceLengthCV=round(cv, 3) if cv is not None else None,
        uniformSentenceRhythm=uniform,
        genericClaimCount=generic_count,
        evidenceMarkers=evidence_markers,
        defenseMarkers=defense_markers,
        defenseCount=defense_count,
    )


SENTENCE_END_RE = re.compile(r"[。！？!?；;]")
NUMBERED_HEADING_RE = re.compile(r"^(?:第[一二三四五六七八九十百千万\d]+[章节部分篇]|[0-9]+(?:\.[0-9]+){0,4}(?:\s+|[、.．]\s*)?[一-鿿A-Za-z])")
# "2019年以来……"、"3种方法……"、"20%的样本……" are sentences that merely start with a number.
NUMBER_STARTS_SENTENCE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?\s*(?:年|月|日|%|％|个|种|项|名|人|次|倍|篇|组|类|位|家|台|款|条|株|只|例|天|小时|分钟|秒)")
CAPTION_RE = re.compile(r"^(?:图|表|Fig\.?|Figure|Table)\s*\d+(?:[.\-－–]\d+)*(?:\s+|[:：.．]\s*|$)", re.I)


def looks_like_numbered_heading(text: str) -> bool:
    """A numbered heading such as "1 绪论" or "第二章 方法": short, no sentence punctuation."""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not NUMBERED_HEADING_RE.match(normalized) or NUMBER_STARTS_SENTENCE_RE.match(normalized):
        return False
    return count_chars(normalized) <= 60 and not SENTENCE_END_RE.search(normalized)


def looks_like_caption(text: str) -> bool:
    """Figure/table captions like "表3.2 实验参数". Body sentences such as "表2给出了……" are kept."""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not CAPTION_RE.match(normalized):
        return False
    return count_chars(normalized) <= 60 and not SENTENCE_END_RE.search(normalized[:-1])


def infer_section_type(text: str) -> SectionType:
    compact = re.sub(r"\s+", "", text or "")
    if re.fullmatch(r"目录|目次|TableofContents", compact, re.I):
        return "other"
    if re.match(r"^(摘要|中文摘要|Abstract)([:：].*)?$", compact, re.I):
        return "abstract"
    if re.match(r"^(关键词|关键字|Keywords?)[:：]?", compact, re.I):
        return "keywords"
    if re.match(r"^(结论|总结|结束语|展望|Conclusion)([:：].*)?$", compact, re.I):
        return "conclusion"
    if re.match(r"^(参考文献|References)$", compact, re.I):
        return "references"
    if looks_like_numbered_heading(text):
        return "chapter_title"
    return "body"


def is_standalone_heading(text: str, section_type: SectionType) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if section_type == "abstract":
        return bool(re.fullmatch(r"摘要|中文摘要|Abstract", compact, re.I))
    if section_type == "keywords":
        return bool(re.fullmatch(r"关键词|关键字|Keywords?[:：]?", compact, re.I))
    if section_type == "conclusion":
        return bool(re.fullmatch(r"结论|总结|结束语|展望|Conclusion", compact, re.I))
    if section_type == "references":
        return bool(re.fullmatch(r"参考文献|References", compact, re.I))
    return False


def importance_for(section_type: SectionType) -> Importance:
    if section_type in ("abstract", "conclusion"):
        return "high"
    if section_type in ("references", "keywords", "chapter_title"):
        return "low"
    return "medium"


def is_detectable(section_type: SectionType) -> bool:
    return section_type in ("abstract", "body", "conclusion")


def is_toc_entry(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    if re.fullmatch(r"目录|目次|TableofContents", compact, re.I):
        return True
    if re.match(r"^(目录|目次)", compact) and re.search(r"(?:摘要|Abstract|第[一二三四五六七八九十百千万\d]+章|[0-9]+(?:\.[0-9]+){1,4})", compact, re.I):
        return True
    return bool(
        re.match(
            r"^(摘要|Abstract|ABSTRACT|第[一二三四五六七八九十百千万\d]+章|[0-9]+(?:\.[0-9]+){1,4}).{0,80}(?:[ivxlcdm]+|\d+)$",
            compact,
            re.I,
        )
    )


def has_sentence_end(text: str) -> bool:
    """CJK sentence punctuation, or an English sentence: eight or more words ending a clause with a full stop."""
    text = text or ""
    if re.search(r"[。！？!?；;]", text):
        return True
    return len(text.split()) >= 8 and bool(re.search(r"[A-Za-z0-9)\]][.](?:\s|$)", text))


def is_cover_or_metadata(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact or len(compact) <= 2:
        return True
    if re.search(r"原创性声明|授权声明|使用授权|版权|学位论文|毕业论文|学校代码|分类号|密级|学号|作者签名|导师签名|指导教师|学院|专业|研究方向|答辩委员会|论文题目|英文题目", compact):
        return True
    if len(compact) <= 260 and not has_sentence_end(text):
        return True
    return bool(re.fullmatch(r"摘要|中文摘要|Abstract|关键词|关键字|Keywords?|目录|目次|参考文献|References", compact, re.I))


def strip_section_label(text: str, section_type: SectionType) -> str:
    normalized = (text or "").strip()
    if section_type == "abstract":
        return re.sub(r"^(?:摘\s*要|中文摘要|Abstract)\s*[:：]?\s*", "", normalized, flags=re.I).strip() or normalized
    if section_type == "conclusion":
        return re.sub(r"^(?:结论|总结|结束语|展望|Conclusion)\s*[:：]?\s*", "", normalized, flags=re.I).strip() or normalized
    return normalized


def is_non_content_text(text: str, section_type: SectionType | None = None) -> bool:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return True
    if section_type and not is_detectable(section_type):
        return True
    if is_toc_entry(normalized):
        return True
    if re.match(r"^(?:关键词|关键字|Keywords?)[:：]?", compact, re.I):
        return True
    if re.fullmatch(r"参考文献|References", compact, re.I):
        return True
    if looks_like_numbered_heading(normalized):
        return True
    if count_chars(normalized) <= 60 and re.match(r"^(?:\([一二三四五六七八九十\d]+\)|（[一二三四五六七八九十\d]+）|[一二三四五六七八九十\d]+[、.．])", normalized) and not re.search(r"[。！？!?；;，,：:]", normalized):
        return True
    if looks_like_caption(normalized):
        return True
    return False


def split_paragraph(paragraph: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    normalized = paragraph.strip()
    if count_chars(normalized) <= max_chars:
        return [normalized]
    pieces: list[str] = []
    current = ""
    for sentence in SENTENCE_SPLIT_RE.split(normalized):
        sentence = sentence.strip()
        if not sentence:
            continue
        if current and count_chars(current + sentence) > max_chars:
            pieces.append(current.strip())
            current = sentence
        else:
            current = join_sentences(current, sentence)
    if current.strip():
        pieces.append(current.strip())
    return pieces or [normalized[:max_chars]]


def compact_chunks(chunks: list[Chunk], max_chars: int = MAX_CHARS_PER_CHUNK) -> list[Chunk]:
    compacted: list[Chunk] = []
    pending: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        text = str(pending["text"])
        compacted.append(
            Chunk(
                chunkId=f"chunk-{len(compacted) + 1:04d}",
                sectionType=pending["sectionType"],
                sectionTitle=pending.get("sectionTitle"),
                text=text,
                charCount=count_chars(text),
                importance=pending["importance"],
                traceFeatures=scan_trace_features(text),
            )
        )
        pending = None

    for chunk in chunks:
        if not is_detectable(chunk.sectionType):
            flush()
            continue
        if (
            pending
            and pending["sectionType"] == chunk.sectionType
            and pending["importance"] == chunk.importance
            and (pending.get("sectionTitle") or "") == (chunk.sectionTitle or "")
            and count_chars(str(pending["text"])) + chunk.charCount <= max_chars
            and count_chars(str(pending["text"])) < MERGE_BELOW_CHARS
            and chunk.charCount < MERGE_BELOW_CHARS
        ):
            pending["text"] = f"{pending['text']}\n{chunk.text}"
            continue
        flush()
        pending = {
            "sectionType": chunk.sectionType,
            "sectionTitle": chunk.sectionTitle,
            "text": chunk.text,
            "importance": chunk.importance,
        }
    flush()
    return compacted


def build_chunks(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[Chunk]:
    paragraphs = normalize_paragraphs(text)
    chunks: list[Chunk] = []
    current_title = ""
    current_type: SectionType = "body"
    expect_keyword_payload = False
    before_main = True
    in_toc = False

    for paragraph in paragraphs:
        inferred = infer_section_type(paragraph)
        compact = re.sub(r"\s+", "", paragraph)

        if re.fullmatch(r"目录|目次|TableofContents", compact, re.I):
            in_toc = True
            expect_keyword_payload = False
            current_type = "other"
            continue

        if inferred == "chapter_title":
            if in_toc and is_toc_entry(paragraph):
                continue
            in_toc = False
            before_main = False
            current_title = paragraph[:120]
            current_type = "conclusion" if re.search(r"结论|总结|展望|Conclusion", paragraph, re.I) else "body"
            expect_keyword_payload = False
            continue

        section_type = "keywords" if inferred == "body" and expect_keyword_payload else inferred if inferred != "body" else current_type
        standalone = is_standalone_heading(paragraph, inferred)
        if standalone and inferred in ("abstract", "keywords", "conclusion", "references"):
            current_title = paragraph[:120]
            expect_keyword_payload = inferred == "keywords"
            current_type = "body" if inferred == "keywords" else inferred
            if inferred in ("abstract", "conclusion", "references"):
                in_toc = False
            if inferred in ("abstract", "conclusion"):
                before_main = False
            continue
        if inferred != "keywords" or not standalone:
            expect_keyword_payload = False

        if in_toc and (is_toc_entry(paragraph) or count_chars(paragraph) < 80):
            continue
        if not is_detectable(section_type):
            continue
        if before_main and is_cover_or_metadata(paragraph):
            continue

        stripped = strip_section_label(paragraph, section_type)
        if is_non_content_text(stripped, section_type):
            continue
        before_main = False

        for piece in split_paragraph(stripped, max_chars=max_chars):
            char_count = count_chars(piece)
            if char_count < REPORT_FRAGMENT_MIN_CHARS:
                continue
            chunks.append(
                Chunk(
                    chunkId=f"chunk-{len(chunks) + 1:04d}",
                    sectionType=section_type,
                    sectionTitle=current_title or None,
                    text=piece,
                    charCount=char_count,
                    importance=importance_for(section_type),
                    traceFeatures=scan_trace_features(piece),
                )
            )

    return compact_chunks(chunks, max_chars=max_chars)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def w_tag(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def owning_paragraph(element: Any) -> Any:
    parent = element.getparent()
    while parent is not None and parent.tag != w_tag("p"):
        parent = parent.getparent()
    return parent


def paragraph_units(paragraph_element: Any) -> list[tuple[str, Any, int]]:
    """Visible characters of one paragraph as (char, element, offset).

    Shared by the scanner and the rewriter so both see exactly the same text. Unlike
    python-docx's ``Paragraph.text`` this also covers runs inside tracked insertions,
    smart tags, simple fields and inline content controls, and it never mixes in text
    from a text box anchored inside the paragraph.
    """
    units: list[tuple[str, Any, int]] = []
    for element in paragraph_element.iter(w_tag("t"), w_tag("tab"), w_tag("br"), w_tag("cr"), w_tag("noBreakHyphen")):
        if owning_paragraph(element) is not paragraph_element:
            continue
        if element.tag == w_tag("t"):
            for offset, char in enumerate(element.text or ""):
                units.append((char, element, offset))
        elif element.getparent() is not None and element.getparent().tag == w_tag("r"):
            # w:tab can also be a tab-stop definition under w:pPr/w:tabs; only run content counts.
            char = {"tab": "\t", "br": "\n", "cr": "\n", "noBreakHyphen": "-"}[element.tag.rsplit("}", 1)[1]]
            units.append((char, element, -1))
    return units


def paragraph_element_text(paragraph_element: Any) -> str:
    return "".join(char for char, _element, _offset in paragraph_units(paragraph_element))


def iter_body_paragraph_elements(document: Any, include_tables: bool = True) -> Iterable[Any]:
    """Every body paragraph in document order: top level, content controls, tables, text boxes.

    Fallback copies of text boxes (mc:Fallback) are skipped so their text is not seen twice.
    """
    for paragraph_element in document.element.body.iter(w_tag("p")):
        ancestor = paragraph_element.getparent()
        skip = False
        while ancestor is not None:
            if ancestor.tag == MC_FALLBACK or (not include_tables and ancestor.tag == w_tag("tbl")):
                skip = True
                break
            ancestor = ancestor.getparent()
        if not skip:
            yield paragraph_element


def read_docx_text(path: Path, include_tables: bool = False) -> tuple[str, dict[str, str]]:
    try:
        from docx import Document  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("python-docx is required for reading DOCX files: python -m pip install python-docx") from exc

    document = Document(str(path))
    # Keep document order. Tables are structured data rather than prose, so they are skipped
    # by default instead of being appended after the references as before.
    lines = [
        text.strip()
        for text in (paragraph_element_text(p) for p in iter_body_paragraph_elements(document, include_tables=include_tables))
        if text.strip()
    ]
    props = document.core_properties
    metadata = {
        "title": (props.title or "").strip(),
        "author": (props.author or "").strip(),
        "subject": (props.subject or "").strip(),
    }
    return "\n".join(lines), metadata


# --- LaTeX sources -----------------------------------------------------------------------------
# A light-weight LaTeX-to-prose reader so Overleaf projects can be scanned without converting
# them to DOCX first. It keeps paragraph boundaries and headings, numbers citations in order of
# first use, and drops floats, display math, code listings and the bibliography.

TEX_DROP_ENVS = (
    "figure", "figure*", "table", "table*", "equation", "equation*", "align", "align*", "gather",
    "gather*", "multline", "multline*", "eqnarray", "eqnarray*", "displaymath", "lstlisting",
    "verbatim", "minted", "tikzpicture", "algorithm", "algorithmic", "thebibliography", "comment",
)
TEX_TABLE_ENVS = ("tabular", "tabular*", "tabularx", "longtable", "tabulary")
TEX_DROP_CMDS = {
    "label", "vspace", "hspace", "bibliography", "bibliographystyle", "includegraphics", "todo",
    "url", "phantomsection", "noindent", "centering", "clearpage", "newpage", "pagebreak",
    "par", "smallskip", "medskip", "bigskip", "maketitle", "tableofcontents", "appendix",
    "caption", "nocite", "addcontentsline", "setlength", "linewidth", "raggedright", "hline",
    "toprule", "midrule", "bottomrule", "newline", "linebreak", "item",
}
TEX_REF_CMDS = {"ref", "cref", "Cref", "autoref", "eqref", "pageref", "nameref", "Sref"}
TEX_CITE_RE = re.compile(r"^(?:cite|citep|citet|citealp|citealt|autocite|parencite|textcite|footcite)\*?$")
TEX_HEADING_RE = re.compile(r"^[A-Za-z]*(?:part|chapter|section)\*?$")
TEX_RUNIN_RE = re.compile(r"^(?:sub)*paragraph\*?$")
TEX_SPECIAL_HEADINGS = re.compile(r"^(?:abstract|keywords?|conclusions?|references|bibliography)$", re.I)
TEX_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]*)\}")


def strip_tex_comments(src: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in src.splitlines())


def find_tex_main(path: Path) -> Path:
    if path.is_file():
        return path
    candidates = sorted(path.glob("*.tex"), key=lambda item: (item.name != "main.tex", item.name))
    for candidate in candidates:
        if "\\documentclass" in strip_tex_comments(candidate.read_text(encoding="utf-8", errors="replace")):
            return candidate
    raise RuntimeError(f"no .tex file with \\documentclass found in {path}")


def expand_tex_inputs(path: Path, root: Path, seen: set[Path] | None = None) -> str:
    seen = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in seen:
        return ""
    seen.add(resolved)
    src = strip_tex_comments(path.read_text(encoding="utf-8", errors="replace"))

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        child = root / (name if name.endswith(".tex") else f"{name}.tex")
        return expand_tex_inputs(child, root, seen) if child.is_file() else ""

    return TEX_INPUT_RE.sub(replace, src)


def read_tex_group(src: str, start: int, open_char: str = "{", close_char: str = "}") -> tuple[str, int]:
    """Return the balanced group starting at src[start] == open_char and the index after it."""
    depth = 0
    for index in range(start, len(src)):
        char = src[index]
        if char == "\\":
            continue
        if char == open_char and (index == 0 or src[index - 1] != "\\"):
            depth += 1
        elif char == close_char and src[index - 1] != "\\":
            depth -= 1
            if depth == 0:
                return src[start + 1 : index], index + 1
    return src[start + 1 :], len(src)


def read_tex_args(src: str, index: int) -> tuple[list[str], int]:
    """Skip optional [..] arguments and collect consecutive {..} arguments after a command."""
    args: list[str] = []
    while True:
        probe = index
        while probe < len(src) and src[probe] in " \t":
            probe += 1
        if probe < len(src) and src[probe] == "[" and not args:
            _, index = read_tex_group(src, probe, "[", "]")
        elif probe < len(src) and src[probe] == "{":
            arg, index = read_tex_group(src, probe)
            args.append(arg)
        else:
            return args, index


class SectionNumberer:
    """Turn source headings into "1 Title" / "1.2 Title" lines, the form build_chunks treats as headings."""

    def __init__(self) -> None:
        self.section = 0
        self.subsection = 0

    def heading(self, title: str, level: int) -> str:
        title = re.sub(r"\s+", " ", title).strip().rstrip(" .:-–—#")
        title = re.sub(r"[。！？!?；;]", "", title)
        if not title:
            return "\n"
        if TEX_SPECIAL_HEADINGS.match(title):
            return f"\n\n{title}\n\n"
        if level <= 1:
            self.section += 1
            self.subsection = 0
            return f"\n\n{self.section} {title}\n\n"
        self.subsection += 1
        return f"\n\n{self.section}.{self.subsection} {title}\n\n"


class TexReader:
    def __init__(self, include_tables: bool = False) -> None:
        self.include_tables = include_tables
        self.citations: dict[str, int] = {}
        self.numberer = SectionNumberer()

    def heading(self, title: str, level: int) -> str:
        return self.numberer.heading(self.inline(title), level)

    def cite(self, keys: str) -> str:
        numbers = []
        for key in (item.strip() for item in keys.split(",")):
            if key:
                numbers.append(self.citations.setdefault(key, len(self.citations) + 1))
        return f"[{', '.join(map(str, numbers))}]" if numbers else ""

    def inline(self, src: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(src):
            char = src[index]
            if char == "\\":
                match = re.match(r"\\([A-Za-z]+\*?|.)", src[index:])
                name = match.group(1) if match else ""
                holder = [index + (len(match.group(0)) if match else 1)]
                out.append(self.command(name, src, holder))
                index = holder[0]
            elif char == "$":
                display = src.startswith("$$", index)
                end = src.find("$$" if display else "$", index + (2 if display else 1))
                end = len(src) if end < 0 else end
                if not display:
                    out.append(self.math(src[index + 1 : end]))
                index = end + (2 if display else 1)
            elif char in "{}":
                index += 1
            elif char == "~":
                out.append(" ")
                index += 1
            elif char == "&":
                out.append(" ")
                index += 1
            else:
                out.append(char)
                index += 1
        text = "".join(out)
        text = text.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”")
        return text

    def math(self, src: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"\\([A-Za-z]+)", r" \1 ", src).replace("{", "").replace("}", "")).strip()

    def command(self, name: str, src: str, holder: list[int]) -> str:
        index = holder[0]
        if name in ("%", "&", "_", "#", "$", "{", "}"):
            return name
        if name == "\\":
            return " "
        if name in (",", ";", ":", " ", "!", "/", "@"):
            return " " if name in (",", ";", ":", " ") else ""
        if name in ("ldots", "dots"):
            return "…"
        if name == "(":
            end = src.find("\\)", index)
            end = len(src) if end < 0 else end
            holder[0] = end + 2
            return self.math(src[index:end])
        if name == "[":
            end = src.find("\\]", index)
            holder[0] = len(src) if end < 0 else end + 2
            return ""
        if name in ("begin", "end"):
            _, holder[0] = read_tex_args(src, index)
            return "\n"
        args, holder[0] = read_tex_args(src, index)
        if TEX_CITE_RE.match(name):
            return self.cite(args[-1]) if args else ""
        if name in TEX_REF_CMDS:
            return "(ref)"
        if name in TEX_DROP_CMDS:
            return "\n" if name == "item" else ""
        if name == "href":
            return self.inline(args[1]) if len(args) > 1 else ""
        if name == "footnote":
            return f" ({self.inline(args[0])})" if args else ""
        if TEX_HEADING_RE.match(name):
            # \section, \chapter and custom wrappers such as \tsection are level 1; any \sub... is level 2.
            return self.heading(args[0], 2 if "subsection" in name else 1) if args else ""
        if TEX_RUNIN_RE.match(name):
            return self.heading(args[0], 2) if args else ""
        return self.inline(args[0]) if args else ""

    def paragraph_runin(self, paragraph: str) -> str:
        """Treat a paragraph opening with a short bold label ("\\textbf{Applications.} ...") as a heading."""
        match = re.match(r"^\s*(?:\\noindent\s*)?\\textbf\s*\{", paragraph)
        if not match:
            return paragraph
        label, end = read_tex_group(paragraph, match.end() - 1)
        rest = paragraph[end:].strip()
        clean_label = re.sub(r"\s+", " ", self.inline(label)).strip().rstrip(" .:-–—")
        if not rest:
            # A bold line on its own is a heading only when it names a standard section ("Abstract -").
            return f"\\section*{{{label}}}" if TEX_SPECIAL_HEADINGS.match(clean_label) else paragraph
        if count_chars(clean_label) > 60:
            return paragraph
        if re.match(r"^keywords?$", clean_label, re.I):
            return f"Keywords: {rest}"
        return f"\\paragraph{{{label}}} {rest}"

    def read(self, body: str) -> str:
        for env in TEX_DROP_ENVS:
            body = re.sub(rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}", "\n", body, flags=re.S)
        for env in TEX_TABLE_ENVS:
            # With --include-tables every table row becomes its own paragraph; otherwise tables are dropped.
            pattern = rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}"
            keep_rows = lambda m: "\n\n" + re.sub(r"\\\\(?:\[[^\]]*\])?", "\n\n", m.group(0)) + "\n\n"
            body = re.sub(pattern, keep_rows if self.include_tables else "\n", body, flags=re.S)
        body = re.sub(r"\\begin\{abstract\}", r"\n\n\\section*{Abstract}\n\n", body)
        paragraphs = [self.paragraph_runin(p) for p in re.split(r"\n\s*\n", body)]
        text = self.inline("\n\n".join(paragraphs))
        lines = [re.sub(r"\s+", " ", block).strip() for block in re.split(r"\n\s*\n", text)]
        return "\n".join(line for line in lines if line)


def read_tex_text(path: Path, include_tables: bool = False) -> tuple[str, dict[str, str]]:
    main = find_tex_main(path)
    src = expand_tex_inputs(main, main.parent)
    metadata = {"title": "", "author": "", "subject": ""}
    for key in ("title", "author"):
        match = re.search(rf"\\{key}\s*(?:\[[^\]]*\])?\s*\{{", src)
        if match:
            raw, _ = read_tex_group(src, match.end() - 1)
            metadata[key] = re.sub(r"\s+", " ", TexReader().inline(raw)).strip()
    begin = src.find("\\begin{document}")
    end = src.find("\\end{document}")
    body = src[begin + len("\\begin{document}") if begin >= 0 else 0 : end if end >= 0 else len(src)]
    return TexReader(include_tables=include_tables).read(body), metadata


# --- Markdown, HTML, PDF and plain text ---------------------------------------------------------

MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
MD_TABLE_RULE_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


def markdown_inline(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(\*\*|__|\*|_|~~|`)(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    return text


def markdown_to_text(src: str, include_tables: bool = False) -> str:
    src = re.sub(r"\A---\n.*?\n---\n", "", src, flags=re.S)  # YAML front matter
    src = re.sub(r"^(```|~~~).*?^\1\s*$", "\n", src, flags=re.S | re.M)  # fenced code
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    numberer = SectionNumberer()
    # A document with a single H1 uses it as its title; sections then start at H2.
    single_title = len(re.findall(r"^\s{0,3}#\s+", src, flags=re.M)) == 1
    out: list[str] = []
    for line in src.splitlines():
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        if heading and single_title and len(heading.group(1)) == 1:
            out.append(f"\n\n{markdown_inline(heading.group(2)).strip()}\n\n")
        elif heading:
            out.append(numberer.heading(markdown_inline(heading.group(2)), len(heading.group(1)) - 1 or 1))
        elif MD_TABLE_RULE_RE.match(line):
            continue
        elif MD_TABLE_ROW_RE.match(line):
            if include_tables:
                out.append("\n" + " ".join(cell.strip() for cell in line.strip().strip("|").split("|")) + "\n")
        elif re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            out.append("\n" + markdown_inline(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)) + "\n")
        elif re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", line):
            out.append("\n")
        else:
            out.append(markdown_inline(re.sub(r"^\s*>\s?", "", line)))
    return plain_text_paragraphs("\n".join(out))


def html_to_text(src: str, include_tables: bool = False) -> str:
    from html.parser import HTMLParser

    class Extractor(HTMLParser):
        skip_tags = {"script", "style", "noscript", "svg", "head", "nav", "footer"}
        block_tags = {"p", "div", "section", "article", "li", "br", "blockquote", "tr", "pre", "ul", "ol"}

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.skip = 0
            self.table = 0
            self.numberer = SectionNumberer()
            self.heading: list[str] | None = None

        def handle_starttag(self, tag: str, attrs: Any) -> None:
            if tag in self.skip_tags:
                self.skip += 1
            elif tag == "table":
                self.table += 1
            elif re.fullmatch(r"h[1-6]", tag):
                self.heading = []
            if tag in self.block_tags:
                self.parts.append("\n\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in self.skip_tags:
                self.skip = max(0, self.skip - 1)
            elif tag == "table":
                self.table = max(0, self.table - 1)
            elif re.fullmatch(r"h[1-6]", tag) and self.heading is not None:
                self.parts.append(self.numberer.heading("".join(self.heading), max(1, int(tag[1]) - 1)))
                self.heading = None
            if tag in self.block_tags or tag in ("td", "th"):
                self.parts.append("\n\n" if tag != "td" and tag != "th" else " ")

        def handle_data(self, data: str) -> None:
            if self.skip or (self.table and not include_tables):
                return
            (self.heading if self.heading is not None else self.parts).append(data)

    extractor = Extractor()
    extractor.feed(src)
    return plain_text_paragraphs("".join(extractor.parts))


def plain_text_paragraphs(src: str) -> str:
    """Blank lines separate paragraphs; single newlines inside a paragraph are soft wraps."""
    src = re.sub(r"(?<=[A-Za-z])-\n(?=[a-z])", "", src.replace("\r\n", "\n").replace("\r", "\n"))
    blocks = [re.sub(r"\s+", " ", block).strip() for block in re.split(r"\n\s*\n", src)]
    return "\n".join(block for block in blocks if block)


def read_pdf_text(path: Path) -> tuple[str, dict[str, str]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("pypdf is required for reading PDF files: python -m pip install pypdf") from exc

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    info = reader.metadata or {}
    metadata = {
        "title": str(info.get("/Title") or "").strip(),
        "author": str(info.get("/Author") or "").strip(),
        "subject": str(info.get("/Subject") or "").strip(),
    }
    return plain_text_paragraphs("\n\n".join(pages)), metadata


EMPTY_METADATA = {"title": "", "author": "", "subject": ""}


def read_source_text(path: Path, include_tables: bool = False) -> tuple[str, dict[str, str]]:
    if not path.exists():
        raise RuntimeError(f"source not found: {path}")
    suffix = path.suffix.lower()
    if path.is_dir() or suffix == ".tex":
        return read_tex_text(path, include_tables=include_tables)
    if suffix == ".docx":
        return read_docx_text(path, include_tables=include_tables)
    if suffix == ".pdf":
        return read_pdf_text(path)
    src = path.read_text(encoding="utf-8", errors="replace")
    if suffix in (".md", ".markdown", ".mdx", ".rmd", ".qmd"):
        return markdown_to_text(src, include_tables=include_tables), dict(EMPTY_METADATA)
    if suffix in (".html", ".htm", ".xhtml"):
        return html_to_text(src, include_tables=include_tables), dict(EMPTY_METADATA)
    return plain_text_paragraphs(src), dict(EMPTY_METADATA)


def is_probable_document_title(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    compact = re.sub(r"\s+", "", normalized)
    if not (4 <= count_chars(normalized) <= 80):
        return False
    if infer_section_type(normalized) != "body":
        return False
    if is_toc_entry(normalized) or is_non_content_text(normalized):
        return False
    if re.search(r"[。！？!?；;]", normalized):
        return False
    if re.search(
        r"原创性声明|授权声明|使用授权|版权|学位论文|毕业论文|学校代码|分类号|密级|学号|"
        r"作者签名|导师签名|指导教师|学院|专业|研究方向|答辩委员会|论文题目|英文题目",
        compact,
    ):
        return False
    return True


def summarize_title(path: Path, text: str, explicit_title: str | None = None, metadata_title: str | None = None) -> str:
    if explicit_title and explicit_title.strip():
        return explicit_title.strip()[:120]
    if metadata_title and metadata_title.strip():
        return metadata_title.strip()[:120]
    for line in normalize_paragraphs(text):
        inferred = infer_section_type(line)
        if inferred in ("abstract", "chapter_title", "conclusion", "references"):
            break
        if is_probable_document_title(line):
            return line[:120]
    return path.stem or "untitled"


def scan_source(
    path: Path | None,
    title: str | None = None,
    author: str | None = None,
    max_chars: int = MAX_CHARS_PER_CHUNK,
    include_tables: bool = False,
    text: str | None = None,
) -> dict[str, Any]:
    """Scan a file or directory, or raw ``text`` (pasted material) when ``path`` is None."""
    if path is None:
        text, metadata = plain_text_paragraphs(text or ""), dict(EMPTY_METADATA)
        source_path, title_path = "", Path(title or "pasted text")
    else:
        text, metadata = read_source_text(path, include_tables=include_tables)
        source_path, title_path = str(path.resolve()), path
    chunks = build_chunks(text, max_chars=max_chars)
    mark_repeated_guard_phrases(chunks)
    return {
        "schemaVersion": 1,
        "tool": "AI-check",
        "sourcePath": source_path,
        "documentTitle": summarize_title(title_path, text, explicit_title=title, metadata_title=metadata.get("title")),
        "author": author or metadata.get("author") or "unknown",
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "totalChars": sum(chunk.charCount for chunk in chunks),
        "chunking": {"maxCharsPerChunk": max_chars, "minReportChars": REPORT_FRAGMENT_MIN_CHARS},
        "chunks": [chunk_to_dict(chunk) for chunk in chunks],
    }


def mark_repeated_guard_phrases(chunks: list[Chunk], min_uses: int = 2) -> None:
    """Flag chunks that reuse a guard phrase ("under the original assumptions") the material repeats."""
    uses: dict[str, int] = {}
    per_chunk: list[set[str]] = []
    for chunk in chunks:
        found = [re.sub(r"\s+", " ", match.group(0).lower()) for match in GUARD_PHRASE_RE.finditer(chunk.text)]
        for phrase in found:
            uses[phrase] = uses.get(phrase, 0) + 1
        per_chunk.append(set(found))
    for chunk, phrases in zip(chunks, per_chunk):
        repeated = sorted(phrase for phrase in phrases if uses[phrase] >= min_uses)
        if repeated:
            signal = f"repeated guard phrase: '{repeated[0]}' ({uses[repeated[0]]}x in material)"
            chunk.traceFeatures.riskSignals = unique_limited([*chunk.traceFeatures.riskSignals, signal])


def chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    data = asdict(chunk)
    data["traceFeatures"] = asdict(chunk.traceFeatures)
    return data


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize_results(payload: Any) -> list[Result]:
    raw_results = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_results, list):
        raise ValueError("results JSON must be a list or an object with a results list")

    results: list[Result] = []
    for item in raw_results:
        if not isinstance(item, dict):
            raise ValueError("each result must be an object")
        raw_score = item.get("aiScore", item.get("aigcValue"))  # aigcValue: legacy results files
        try:
            value = float(raw_score)
        except (TypeError, ValueError):
            raise ValueError(f"aiScore missing or not a number for {item.get('chunkId')}") from None
        if 1 < value <= 100:
            value = value / 100  # assistants sometimes answer 0-100 instead of 0-1
        if not math.isfinite(value) or value < 0 or value > 1:
            raise ValueError(f"aiScore must be 0..1 for {item.get('chunkId')}")
        sensitivity = str(item.get("sensitivity") or "medium").strip().lower()
        verdict = str(item.get("verdict") or "suspicious").strip().lower()
        if sensitivity not in ("low", "medium", "high"):
            raise ValueError(f"invalid sensitivity for {item.get('chunkId')}")
        if verdict not in ("human", "suspicious", "ai"):
            raise ValueError(f"invalid verdict for {item.get('chunkId')}")
        signals = item.get("signals") or []
        if isinstance(signals, str):
            signals = [part.strip() for part in re.split(r"[,，、\n]+", signals) if part.strip()]
        results.append(
            Result(
                chunkId=str(item.get("chunkId") or "").strip(),
                sensitivity=sensitivity,  # type: ignore[arg-type]
                aiScore=round(value, 3),
                verdict=verdict,  # type: ignore[arg-type]
                reason=str(item.get("reason") or "").strip(),
                signals=[str(signal).strip() for signal in signals if str(signal).strip()],
            )
        )
    return results


def comparable_text(value: str) -> str:
    return re.sub(r"(?:\s|\u00a0|\u200b|\u200c|\u200d|\u2060|\u2063)+", "", value or "").strip()


def build_report_fragments(text: str) -> list[str]:
    paragraphs = normalize_paragraphs(text)
    fragments: list[str] = []
    for paragraph in paragraphs:
        if is_non_content_text(paragraph):
            continue
        current = ""
        for sentence in SENTENCE_SPLIT_RE.split(paragraph):
            normalized = sentence.strip()
            if not normalized:
                continue
            next_text = join_sentences(current, normalized)
            if current and count_chars(next_text) > REPORT_FRAGMENT_MAX_CHARS:
                fragments.append(current)
                current = normalized
            else:
                current = next_text
        if current:
            fragments.append(current)

    fallback = [paragraph for paragraph in paragraphs if not is_non_content_text(paragraph)]
    candidates = fragments or fallback
    out: list[str] = []
    for fragment in candidates:
        out.extend(split_long_fragment(fragment))
    return [fragment for fragment in out if count_chars(fragment) >= REPORT_FRAGMENT_MIN_CHARS]


def split_long_fragment(fragment: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", fragment or "").strip()
    if not normalized:
        return []
    if count_chars(normalized) <= REPORT_FRAGMENT_MAX_CHARS:
        return [normalized]

    pieces: list[str] = []
    rest = normalized
    while count_chars(rest) > REPORT_FRAGMENT_MAX_CHARS:
        hard_limit = min(len(rest), REPORT_FRAGMENT_MAX_CHARS)
        window = rest[:hard_limit]
        min_boundary = max(48, hard_limit // 2)
        split_at = -1
        for token in ("。", "！", "？", "；", ";", "，", ",", "、", " "):
            index = window.rfind(token)
            if index >= min_boundary:
                split_at = max(split_at, index + len(token))
        if split_at <= 0:
            split_at = hard_limit
        piece = rest[:split_at].strip()
        if piece:
            pieces.append(piece)
        rest = rest[split_at:].strip()
        if not rest:
            break
    if rest:
        pieces.append(rest)
    return pieces


def report_reason(result: Result) -> str:
    reason = result.reason.strip()
    signals = [signal.strip() for signal in result.signals if signal.strip()]
    if not signals:
        return reason
    return f"{reason} Signals: {', '.join(signals)}." if reason else f"Signals: {', '.join(signals)}."


def percent(value: float) -> str:
    return f"{round(max(0.0, min(1.0, value)) * 1000) / 10:.1f}%"


def get_report_rows(scan: dict[str, Any], results: list[Result]) -> list[dict[str, Any]]:
    result_by_chunk = {result.chunkId: result for result in results}
    known = {str(chunk.get("chunkId") or "") for chunk in scan.get("chunks", [])}
    unknown = sorted(set(result_by_chunk) - known)
    if unknown:
        print(f"AI-check warning: results reference unknown chunkIds (ignored): {', '.join(unknown[:10])}", file=sys.stderr)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in scan.get("chunks", []):
        result = result_by_chunk.get(str(chunk.get("chunkId") or ""))
        if not result or result.aiScore < REPORT_MIN_VALUE:
            continue
        if chunk.get("sectionType") not in ("abstract", "body", "conclusion"):
            continue
        for text in build_report_fragments(str(chunk.get("text") or "")):
            normalized = comparable_text(text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append({"chunk": chunk, "result": result, "text": text})
    return rows


def calculate_summary(scan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_chars = int(scan.get("totalChars") or 0)
    if total_chars <= 0:
        total_chars = sum(int(chunk.get("charCount") or count_chars(str(chunk.get("text") or ""))) for chunk in scan.get("chunks", []))
    total_chars = max(1, total_chars)
    suspicious_chars = sum(count_chars(row["text"]) for row in rows)
    weighted_score = sum(count_chars(row["text"]) * row["result"].aiScore for row in rows)
    ai_rate = weighted_score / total_chars
    flagged_share = suspicious_chars / total_chars
    return {
        "aiScore": round(max(0.0, min(1.0, ai_rate)), 4),
        "flaggedShare": round(max(0.0, min(1.0, flagged_share)), 4),
        "humanShare": round(max(0.0, min(1.0, 1 - ai_rate)), 4),
        "flaggedChars": suspicious_chars,
        "totalChars": total_chars,
        "fragmentCount": len(rows),
    }


def render_html(scan: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    detection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = str(scan.get("documentTitle") or "untitled")
    author = str(scan.get("author") or "unknown")
    distribution = "\n".join(
        f'<span class="dist {risk_band(row["result"].aiScore)}" style="height:{max(8, round(12 + row["result"].aiScore * 42))}px"></span>'
        for row in rows
    )
    table_rows = "\n".join(
        f"""<tr>
  <td class="original">
    <div class="original-text">{html.escape(row["text"])}</div>
    <div class="reason">Reason: {html.escape(report_reason(row["result"]))}</div>
  </td>
  <td class="score">AI score: {row["result"].aiScore:.3f}</td>
</tr>"""
        for row in rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>AI-check Report</title>
  <style>
    @page {{ size: A4; margin: 18mm; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #202124; font-family: Arial, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; font-size: 12px; line-height: 1.65; }}
    .page-title {{ text-align: center; font-size: 22px; font-weight: 700; margin: 2mm 0 8mm; }}
    .meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2mm 8mm; border: 1px solid #d9d9d9; padding: 4mm 5mm; margin-bottom: 6mm; }}
    .section-title {{ background: #f2f4f7; border-left: 4px solid #4b89dc; font-size: 15px; font-weight: 700; padding: 2mm 3mm; margin: 5mm 0 3mm; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 3mm; margin-bottom: 5mm; }}
    .metric {{ border: 1px solid #dadce0; min-height: 20mm; padding: 3mm; text-align: center; }}
    .metric strong {{ display: block; color: #d93025; font-size: 20px; line-height: 1.2; }}
    .metric span {{ color: #5f6368; }}
    .distribution {{ height: 22mm; border: 1px solid #dadce0; display: flex; align-items: flex-end; gap: 1px; padding: 2mm; margin-bottom: 5mm; }}
    .dist {{ display: inline-block; width: 5px; min-width: 3px; background: #34a853; }}
    .dist.medium {{ background: #fbbc04; }}
    .dist.high {{ background: #ea4335; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    tr {{ break-inside: avoid; page-break-inside: avoid; }}
    th {{ background: #f7f7f7; font-weight: 700; }}
    th, td {{ border: 1px solid #d9d9d9; vertical-align: top; padding: 2.2mm 2.4mm; }}
    td.original {{ width: 76%; overflow-wrap: anywhere; }}
    .reason {{ margin-top: 1.6mm; color: #6b7280; font-size: 10.5px; line-height: 1.45; }}
    td.score {{ width: 24%; color: #d93025; white-space: nowrap; font-weight: 700; }}
    .notes {{ margin-top: 7mm; color: #4b5563; }}
  </style>
</head>
<body>
  <h1 class="page-title">AI-check Report</h1>
  <section class="meta">
    <div>Checked at: {html.escape(detection_time)}</div>
    <div>Material: {html.escape(title)}</div>
    <div>Author: {html.escape(author)}</div>
    <div>Check type: AI-writing assessment</div>
    <div style="grid-column:1 / -1">Scope: {html.escape(DETECTION_SCOPE)}</div>
  </section>
  <div class="section-title">Result</div>
  <section class="metrics">
    <div class="metric"><strong>{percent(summary["aiScore"])}</strong><span>AI score</span></div>
    <div class="metric"><strong>{percent(summary["flaggedShare"])}</strong><span>Flagged share</span></div>
    <div class="metric"><strong>{percent(summary["humanShare"])}</strong><span>Human share</span></div>
    <div class="metric"><strong>[{summary["flaggedChars"]}]</strong><span>Flagged chars</span></div>
    <div class="metric"><strong>[{summary["totalChars"]}]</strong><span>Total chars</span></div>
  </section>
  <div class="section-title">Flagged fragment distribution</div>
  <section class="distribution">{distribution}</section>
  <table>
    <thead><tr><th style="width:76%">Text</th><th style="width:24%">AI score</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
  <section class="notes">
    <p>Notes:</p>
    <p>AI-check builds this report from the assistant's fragment-by-fragment judgements. The AI score is unrelated to the quality of the text and is for reference only.</p>
    <p>It does not represent the output of Turnitin, GPTZero, CNKI or any other closed detector.</p>
    <p>Fragments are split automatically and may differ from the paragraphs of the source.</p>
  </section>
</body>
</html>
"""


def cjk_font_candidates() -> list[str]:
    candidates = [
        os.environ.get("AI_CHECK_PDF_FONT"),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    return [candidate for candidate in candidates if candidate and Path(candidate).exists()]


def render_pdf(path: Path, scan: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    try:
        from reportlab.lib import colors  # type: ignore
        from reportlab.lib.enums import TA_CENTER, TA_LEFT  # type: ignore
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib.styles import ParagraphStyle  # type: ignore
        from reportlab.lib.units import mm  # type: ignore
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # type: ignore
        from reportlab.pdfbase import pdfmetrics  # type: ignore
        from reportlab.pdfbase.ttfonts import TTFont  # type: ignore
        from reportlab.platypus import Flowable, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("reportlab is required for PDF output: python -m pip install reportlab") from exc

    def register_pdf_font(needs_cjk: bool) -> str:
        if not needs_cjk:
            # Latin-only material reads best in the built-in Helvetica family (with a real bold face).
            pdfmetrics.registerFontFamily("Helvetica", normal="Helvetica", bold="Helvetica-Bold", italic="Helvetica-Oblique", boldItalic="Helvetica-BoldOblique")
            return "Helvetica"
        # reportlab cannot load CFF-outline fonts (e.g. Noto Sans CJK .otf/.ttc, PingFang), so keep
        # trying candidates and fall back to the built-in STSong-Light CID font.
        for cjk_font in cjk_font_candidates():
            try:
                font_name = "AI_CHECK_CJK"
                pdfmetrics.registerFont(TTFont(font_name, cjk_font))
                pdfmetrics.registerFontFamily(font_name, normal=font_name, bold=font_name, italic=font_name, boldItalic=font_name)
                return font_name
            except Exception:
                continue
        fallback = "STSong-Light"
        pdfmetrics.registerFont(UnicodeCIDFont(fallback))
        return fallback

    def risk_palette(value: float) -> tuple[str, Any, Any]:
        band = risk_band(value)
        if band == "high":
            return "High risk", colors.HexColor("#D93025"), colors.HexColor("#FDECEC")
        if band == "medium":
            return "Medium risk", colors.HexColor("#B06000"), colors.HexColor("#FFF4D8")
        return "Low risk", colors.HexColor("#188038"), colors.HexColor("#E6F4EA")

    class DistributionBars(Flowable):
        def __init__(self, values: list[float], height: float = 22 * mm) -> None:
            super().__init__()
            self.values = [max(0.0, min(1.0, float(value))) for value in values]
            self.height = height
            self.width = 0

        def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
            self.width = avail_width
            return avail_width, self.height

        def draw(self) -> None:
            pad = 6
            base_y = pad + 1
            chart_h = self.height - pad * 2 - 1
            self.canv.setFillColor(softer)
            self.canv.setStrokeColor(border)
            self.canv.roundRect(0, 0, self.width, self.height, 6, stroke=1, fill=1)
            self.canv.setStrokeColor(colors.HexColor("#E5EAF1"))
            self.canv.setLineWidth(0.5)
            self.canv.line(pad, base_y, self.width - pad, base_y)
            if not self.values:
                return
            gap = 1.2
            max_bars = max(1, int((self.width - pad * 2) / 2.6))
            values = self.values[:max_bars]
            available = self.width - pad * 2 - gap * max(0, len(values) - 1)
            bar_w = max(1.4, min(5.0, available / max(1, len(values))))
            x = pad
            for value in values:
                _, accent, _tint = risk_palette(value)
                height = max(5, value * chart_h)
                self.canv.setFillColor(accent)
                self.canv.roundRect(x, base_y, bar_w, height, 1.2, stroke=0, fill=1)
                x += bar_w + gap

    report_text = " ".join(
        [str(scan.get("documentTitle") or ""), str(scan.get("author") or "")]
        + [row["text"] + report_reason(row["result"]) for row in rows]
    )
    needs_cjk = bool(re.search(r"[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]", report_text))
    font_name = register_pdf_font(needs_cjk)
    path.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = A4
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="AI-check Report",
        author="AI-check",
    )

    blue = colors.HexColor("#2563EB")
    blue_dark = colors.HexColor("#1D4ED8")
    ink = colors.HexColor("#202124")
    muted = colors.HexColor("#5F6368")
    border = colors.HexColor("#D7DEE8")
    soft = colors.HexColor("#F6F8FB")
    softer = colors.HexColor("#FBFCFE")
    red = colors.HexColor("#D93025")
    green = colors.HexColor("#188038")
    amber = colors.HexColor("#B06000")
    soft_red = colors.HexColor("#FDECEC")
    soft_amber = colors.HexColor("#FFF4D8")
    soft_green = colors.HexColor("#E6F4EA")
    soft_blue = colors.HexColor("#E8F0FE")
    soft_slate = colors.HexColor("#F8FAFC")

    base = ParagraphStyle("AICheckBase", fontName=font_name, fontSize=9.1, leading=13.0, textColor=ink, alignment=TA_LEFT, wordWrap="CJK" if needs_cjk else None)
    title_style = ParagraphStyle("AICheckTitle", parent=base, fontSize=19.2, leading=24, alignment=TA_LEFT, textColor=colors.HexColor("#0F172A"), spaceAfter=1.3 * mm)
    subtitle_style = ParagraphStyle("AICheckSubtitle", parent=base, fontSize=8.7, leading=11.8, alignment=TA_LEFT, textColor=muted)
    meta_style = ParagraphStyle("AICheckMeta", parent=base, fontSize=8.2, leading=11.4, textColor=ink)
    section_style = ParagraphStyle("AICheckSection", parent=base, fontSize=11.3, leading=14.8, textColor=colors.HexColor("#0F172A"))
    metric_value_style = ParagraphStyle("AICheckMetricValue", parent=base, fontSize=16, leading=18.5, alignment=TA_CENTER, textColor=red)
    metric_label_style = ParagraphStyle("AICheckMetricLabel", parent=base, fontSize=7.5, leading=9.8, alignment=TA_CENTER, textColor=muted)
    table_header_style = ParagraphStyle("AICheckTableHeader", parent=base, fontSize=8.5, leading=10.8, alignment=TA_CENTER, textColor=colors.HexColor("#0F172A"))
    body_style = ParagraphStyle("AICheckBody", parent=base, fontSize=8.55, leading=12.4)
    reason_style = ParagraphStyle("AICheckReason", parent=base, fontSize=7.15, leading=9.8, textColor=colors.HexColor("#6B7280"))
    score_style = ParagraphStyle("AICheckScore", parent=base, fontSize=8.25, leading=10.8, alignment=TA_CENTER)
    note_style = ParagraphStyle("AICheckNote", parent=base, fontSize=7.9, leading=11.0, textColor=muted)

    def safe(value: Any) -> str:
        return html.escape(str(value or "")).replace("\n", "<br/>")

    def paragraph(value: Any, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(safe(value), style)

    def pill(text: str, bg: Any, fg: Any) -> Table:
        pill_style = ParagraphStyle(
            "AICheckPill",
            parent=base,
            fontSize=7.2,
            leading=9.2,
            alignment=TA_CENTER,
            textColor=fg,
        )
        table = Table([[Paragraph(safe(text), pill_style)]], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), bg),
                    ("BOX", (0, 0), (-1, -1), 0.45, fg),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return table

    def header_card() -> Table:
        meta_data = [
            [paragraph(f"Checked at: {detection_time}", meta_style), paragraph(f"Material: {title}", meta_style)],
            [paragraph(f"Author: {author}", meta_style), paragraph("Check type: AI-writing assessment", meta_style)],
            [paragraph(f"Scope: {scope}", meta_style), ""],
        ]
        # The header card's content column is doc.width minus the 4mm accent bar and 8pt padding on each side.
        meta_width = doc.width - 4 * mm - 16
        meta_table = Table(meta_data, colWidths=[meta_width * 0.38, meta_width * 0.62], hAlign="LEFT")
        meta_table.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 2), (1, 2)),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.45, border),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E7EDF5")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        content = [
            pill("AI-writing assessment", blue_dark, colors.white),
            Spacer(1, 2.5 * mm),
            Paragraph("AI-check Report", title_style),
            Paragraph("Independent text extraction · selectable-text PDF · for reference only", subtitle_style),
            Spacer(1, 3 * mm),
            meta_table,
        ]
        table = Table([["", content]], colWidths=[4 * mm, doc.width - 4 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), blue_dark),
                    ("BACKGROUND", (1, 0), (1, 0), soft_slate),
                    ("BOX", (0, 0), (-1, -1), 0.55, border),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("RIGHTPADDING", (0, 0), (0, 0), 0),
                    ("LEFTPADDING", (1, 0), (1, 0), 8),
                    ("RIGHTPADDING", (1, 0), (1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (1, 0), (1, 0), 7),
                    ("BOTTOMPADDING", (1, 0), (1, 0), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def section_title(text: str) -> Table:
        table = Table([["", paragraph(text, section_style)]], colWidths=[4 * mm, doc.width - 4 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), blue),
                    ("BACKGROUND", (1, 0), (1, 0), soft),
                    ("BOX", (0, 0), (-1, -1), 0.5, border),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("RIGHTPADDING", (0, 0), (0, 0), 0),
                    ("LEFTPADDING", (1, 0), (1, 0), 8),
                    ("RIGHTPADDING", (1, 0), (1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return table

    def metric_table() -> Table:
        values = [
            (percent(summary["aiScore"]), "AI score", red, soft_red),
            (percent(summary["flaggedShare"]), "Flagged share", amber, soft_amber),
            (percent(summary["humanShare"]), "Human share", green, soft_green),
            (str(summary["flaggedChars"]), "Flagged chars", red, soft_red),
            (str(summary["totalChars"]), "Total chars", blue_dark, soft_blue),
        ]
        value_cells = []
        label_cells = []
        for value, label, color, tint in values:
            value_style = ParagraphStyle(f"AICheckMetricValue{label.replace(' ', '')}", parent=metric_value_style, textColor=color)
            value_cells.append(Paragraph(safe(value), value_style))
            label_cells.append(Paragraph(safe(label), metric_label_style))
        table = Table([value_cells, label_cells], colWidths=[doc.width / 5] * 5, hAlign="LEFT")
        table_style_commands: list[tuple[Any, ...]] = [
            ("BOX", (0, 0), (-1, -1), 0.55, border),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E6ECF4")),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        for index, (_, _, color, tint) in enumerate(values):
            table_style_commands.extend(
                [
                    ("BACKGROUND", (index, 0), (index, 1), tint),
                    ("LINEABOVE", (index, 0), (index, 0), 1.25, color),
                ]
            )
        table.setStyle(
            TableStyle(table_style_commands)
        )
        return table

    detection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = str(scan.get("documentTitle") or "untitled")
    author = str(scan.get("author") or "unknown")
    scope = DETECTION_SCOPE
    fragment_label = f"{summary['fragmentCount']} fragment{'' if summary['fragmentCount'] == 1 else 's'}"

    story: list[Any] = [
        header_card(),
        Spacer(1, 6 * mm),
        section_title("Result"),
        Spacer(1, 3 * mm),
        metric_table(),
        Spacer(1, 6 * mm),
        section_title(f"Flagged fragment distribution ({fragment_label})"),
        Spacer(1, 3 * mm),
        DistributionBars([row["result"].aiScore for row in rows]),
        Spacer(1, 2 * mm),
        Table(
            [[pill("Low risk", soft_green, green), pill("Medium risk", soft_amber, amber), pill("High risk", soft_red, red)]],
            colWidths=[doc.width / 3] * 3,
            hAlign="LEFT",
        ),
        Spacer(1, 2 * mm),
        paragraph("Taller bars mean higher AI scores; colour runs from green to red as risk rises.", note_style),
        Spacer(1, 6 * mm),
        section_title(f"Text / AI score ({fragment_label})"),
        Spacer(1, 3 * mm),
    ]

    table_data: list[list[Any]] = [[paragraph("Text", table_header_style), paragraph("AI score", table_header_style)]]
    for row in rows:
        result: Result = row["result"]
        reason = report_reason(result)
        value = max(0.0, min(1.0, result.aiScore))
        label, accent, tint = risk_palette(value)
        original_cell: list[Any] = [paragraph(row["text"], body_style)]
        if reason:
            original_cell.extend([Spacer(1, 2), paragraph(f"Reason: {reason}", reason_style)])
        score = Paragraph(
            f'<b>{label}</b><br/><font color="{accent.hexval()}">AI score: {value:.3f}</font>',
            score_style,
        )
        table_data.append([original_cell, score])

    report_table = LongTable(table_data, colWidths=[doc.width * 0.74, doc.width * 0.26], repeatRows=1, hAlign="LEFT", splitByRow=1)
    table_style_commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), soft_blue),
        ("BOX", (0, 0), (-1, -1), 0.45, border),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5EAF1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for row_index in range(1, len(table_data)):
        result = rows[row_index - 1]["result"]
        value = max(0.0, min(1.0, result.aiScore))
        _, accent, tint = risk_palette(value)
        table_style_commands.extend(
            [
                ("BACKGROUND", (0, row_index), (-1, row_index), tint),
                ("LINEBEFORE", (1, row_index), (1, row_index), 1.0, accent),
            ]
        )
    report_table.setStyle(TableStyle(table_style_commands))
    story.append(report_table)
    story.extend(
        [
            Spacer(1, 7 * mm),
            section_title("Notes"),
            Spacer(1, 2.5 * mm),
            paragraph("AI-check builds this report from the assistant's fragment-by-fragment judgements. The AI score is unrelated to the quality of the text and is for reference only.", note_style),
            paragraph("It does not represent the output of Turnitin, GPTZero, CNKI or any other closed detector.", note_style),
            paragraph("Fragments are split automatically and may differ from the paragraphs of the source.", note_style),
        ]
    )

    def draw_page(canvas_obj: Any, doc_obj: Any) -> None:
        canvas_obj.saveState()
        header_h = 8.5 * mm
        canvas_obj.setFillColor(soft_slate)
        canvas_obj.rect(0, page_h - header_h, page_w, header_h, stroke=0, fill=1)
        canvas_obj.setStrokeColor(blue_dark)
        canvas_obj.setLineWidth(0.7)
        canvas_obj.line(0, page_h - header_h, page_w, page_h - header_h)
        canvas_obj.setFont(font_name, 7.6)
        canvas_obj.setFillColor(blue_dark)
        canvas_obj.drawString(doc_obj.leftMargin, page_h - 5.6 * mm, "AI-check")
        canvas_obj.setFillColor(muted)
        canvas_obj.drawRightString(page_w - doc_obj.rightMargin, page_h - 5.6 * mm, f"Page {doc_obj.page}")
        footer_y = 10 * mm
        canvas_obj.setStrokeColor(colors.HexColor("#E5E7EB"))
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(doc_obj.leftMargin, footer_y + 4, page_w - doc_obj.rightMargin, footer_y + 4)
        canvas_obj.setFont(font_name, 7.5)
        canvas_obj.setFillColor(muted)
        canvas_obj.drawString(doc_obj.leftMargin, footer_y - 1, "AI-check · reference report")
        canvas_obj.drawRightString(page_w - doc_obj.rightMargin, footer_y - 1, f"Page {doc_obj.page}")
        canvas_obj.restoreState()

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)


def generate_report(scan_path: Path, results_path: Path, out_dir: Path) -> dict[str, Any]:
    scan = load_json(scan_path)
    results = normalize_results(load_json(results_path))
    rows = get_report_rows(scan, results)
    summary = calculate_summary(scan, rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    html_path = out_dir / f"AI-check-report-{timestamp}.html"
    pdf_path = out_dir / f"AI-check-report-{timestamp}.pdf"
    summary_path = out_dir / f"AI-check-summary-{timestamp}.json"

    html_path.write_text(render_html(scan, rows, summary), encoding="utf-8", newline="\n")
    pdf_error = ""
    try:
        render_pdf(pdf_path, scan, rows, summary)
    except Exception as exc:
        pdf_error = str(exc)
        pdf_path = Path("")

    output = {
        **summary,
        "htmlPath": str(html_path.resolve()),
        "pdfPath": str(pdf_path.resolve()) if str(pdf_path) else "",
        "pdfError": pdf_error,
        "reportPath": str(pdf_path.resolve()) if str(pdf_path) else str(html_path.resolve()),
    }
    write_json(summary_path, output)
    output["summaryPath"] = str(summary_path.resolve())
    return output


def command_scan(args: argparse.Namespace) -> int:
    if args.text is not None or args.source == "-":
        text = args.text if args.text is not None else sys.stdin.read()
        data = scan_source(None, title=args.title, author=args.author, max_chars=args.max_chars, text=text)
    elif args.source:
        source = Path(args.source)
        data = scan_source(source, title=args.title, author=args.author, max_chars=args.max_chars, include_tables=args.include_tables)
    else:
        raise ValueError("give a source path, '-' for stdin, or --text")
    if args.out:
        write_json(Path(args.out), data)
    print(json.dumps(data if not args.out else {"scanPath": str(Path(args.out).resolve()), "chunks": len(data["chunks"]), "totalChars": data["totalChars"]}, ensure_ascii=False, indent=2))
    return 0


def command_report(args: argparse.Namespace) -> int:
    output = generate_report(Path(args.scan_json), Path(args.results_json), Path(args.out_dir))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_features(args: argparse.Namespace) -> int:
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    print(json.dumps(asdict(scan_trace_features(text)), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-check: deterministic text scanner and AI-score report generator")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="read any material and write chunk/traceFeatures JSON")
    scan.add_argument(
        "source",
        nargs="?",
        help="DOCX, PDF, Markdown, HTML, plain-text or .tex file, a LaTeX project directory, or '-' for stdin",
    )
    scan.add_argument("--text", help="scan this text directly (pasted material)")
    scan.add_argument("--out", help="output scan JSON path")
    scan.add_argument("--title", help="override document title")
    scan.add_argument("--author", help="override author")
    scan.add_argument("--max-chars", type=int, default=MAX_CHARS_PER_CHUNK, help="maximum Chinese-aware chars per chunk")
    scan.add_argument("--include-tables", action="store_true", help="also scan text inside tables (skipped by default)")
    scan.set_defaults(func=command_scan)

    report = sub.add_parser("report", help="render the HTML/PDF AI-score report from scan JSON and assistant results JSON")
    report.add_argument("scan_json", help="scan JSON path")
    report.add_argument("results_json", help="assistant-provided results JSON path")
    report.add_argument("--out-dir", required=True, help="output directory")
    report.set_defaults(func=command_report)

    features = sub.add_parser("features", help="scan deterministic trace features for text")
    features.add_argument("text", nargs="?", default="", help="text to scan")
    features.add_argument("--file", help="UTF-8 text file to scan")
    features.set_defaults(func=command_features)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"AI-check error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
