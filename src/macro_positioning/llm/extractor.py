from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from macro_positioning.core.models import Evidence, Thesis, ThesisStatus, ViewDirection


# ---------------------------------------------------------------------------
# Lexicon - expanded so we catch analyst shorthand, not just obvious words
# ---------------------------------------------------------------------------

# Map keywords to canonical asset/theme labels. Order here does not matter.
ASSET_KEYWORDS: dict[str, str] = {
    "duration": "rates",
    "treasur": "rates",  # treasury / treasuries
    "bond": "rates",
    "yield": "rates",
    "rate": "rates",
    "curve": "rates",
    "dollar": "usd",
    "usd": "usd",
    "dxy": "usd",
    "gold": "gold",
    "silver": "metals",
    "copper": "metals",
    "commodit": "commodities",
    "equit": "equities",
    "stock": "equities",
    "spx": "equities",
    "s&p": "equities",
    "nasdaq": "equities",
    "oil": "energy",
    "crude": "energy",
    "wti": "energy",
    "brent": "energy",
    "gas": "energy",
    "credit": "credit",
    "spread": "credit",
    "high yield": "credit",
    "em ": "emerging_markets",
    "emerging": "emerging_markets",
    "china": "emerging_markets",
    "bitcoin": "crypto",
    "btc": "crypto",
    "crypto": "crypto",
}

# Theme keywords (broader than assets - macro narratives)
THEME_KEYWORDS: dict[str, str] = {
    "inflation": "inflation",
    "disinflation": "inflation",
    "cpi": "inflation",
    "pce": "inflation",
    "growth": "growth",
    "gdp": "growth",
    "recession": "growth",
    "employment": "labor",
    "payroll": "labor",
    "jobless": "labor",
    "labor": "labor",
    "housing": "housing",
    "fed": "policy",
    "fomc": "policy",
    "ecb": "policy",
    "hike": "policy",
    "cut": "policy",
    "liquidity": "liquidity",
    "qt ": "liquidity",
    "qe ": "liquidity",
    "fiscal": "fiscal",
    "deficit": "fiscal",
    "geopolitic": "geopolitics",
}

BULLISH_MARKERS = (
    "bullish", "supportive", "prefer", "works", "improving", "resilience",
    "upside", "tailwind", "outperform", "overweight", "accumulate", "buy",
    "long ", "cheapen", "attractive", "benign", "stabilizing", "stabilising",
    "troughing", "bottoming", "expand", "breakout",
)
BEARISH_MARKERS = (
    "bearish", "slowing", "rolling over", "tighten", "fatigue", "deterioration",
    "headwind", "underperform", "underweight", "short ", "sell", "downside",
    "drag", "strain", "stress", "expensive", "overbought", "topping", "peaked",
    "roll over", "decelerat", "contract", "breakdown",
)
DISINFLATION_MARKERS = ("disinflation", "easing", "cooling", "declining", "falling")
REINFLATION_MARKERS = ("reinflation", "sticky", "rising", "reaccelerat", "hotter")

HEDGING_MARKERS = ("might", "may ", "could", "possibly", "perhaps", "tentative")
CONVICTION_MARKERS = ("base case", "we think", "prefer", "clearly", "strongly",
                      "convinced", "high conviction", "we like", "we expect")
RISK_MARKERS = ("risk is", "risk to", "upside risk", "downside risk",
                "invalidation", "invalidate", "would change", "break if",
                "watch for", "contingent on")
CATALYST_PREFIXES = ("because", " as ", " if ", "driven by", "owing to",
                     "once ", "when ", "should ", "contingent on")
HORIZON_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"next (\d+)\s*[-to ]*\s*(\d+)?\s*(day|week|month|quarter|year)s?", re.I),
     "explicit"),
    (re.compile(r"(one|two|three|four|five|six)\s*to\s*(\w+)\s*(weeks?|months?|quarters?)", re.I),
     "explicit"),
    (re.compile(r"\b(tactical|tactically|near[- ]term|short[- ]term)\b", re.I), "2-8 weeks"),
    (re.compile(r"\b(medium[- ]term|intermediate)\b", re.I), "1-3 months"),
    (re.compile(r"\b(structural|strategic|long[- ]term|secular)\b", re.I), "6-18 months"),
    (re.compile(r"\b(this|next)\s+quarter\b", re.I), "1-3 months"),
    (re.compile(r"\bcycle\b", re.I), "6-18 months"),
]


class ThesisExtractor:
    def extract(
        self,
        document_id: str,
        source_id: str,
        text: str,
        published_at,
        url: str | None,
    ) -> list[Thesis]:
        raise NotImplementedError


class HeuristicThesisExtractor(ThesisExtractor):
    """Heuristic sentence-level thesis extractor.

    This is intentionally deterministic - it exists so we can prove the data
    flow end-to-end without an LLM in the loop. Real production use should
    call a model via LLMThesisExtractor, but the output schema is identical,
    so downstream memo / validation logic does not care which ran.
    """

    # kept on the class for backwards compat with prior imports
    ASSET_KEYWORDS = ASSET_KEYWORDS
    BULLISH_MARKERS = BULLISH_MARKERS
    BEARISH_MARKERS = BEARISH_MARKERS
    CATALYST_MARKERS = CATALYST_PREFIXES
    RISK_MARKERS = RISK_MARKERS

    def __init__(self, min_confidence: float = 0.40) -> None:
        self.min_confidence = min_confidence

    def extract(
        self,
        document_id: str,
        source_id: str,
        text: str,
        published_at,
        url: str | None,
    ) -> list[Thesis]:
        sentences = split_sentences(text)
        risks_in_doc = infer_risks(sentences)
        theses: list[Thesis] = []
        for sentence in sentences:
            direction = infer_direction(sentence)
            if direction is None:
                continue
            assets = infer_assets(sentence)
            theme = infer_theme(sentence, assets)
            confidence = infer_confidence(sentence, assets)
            # Drop noise below threshold unless it has explicit assets
            if confidence < self.min_confidence and not assets:
                continue
            thesis = Thesis(
                thesis_id=thesis_id_for(document_id, sentence),
                thesis=sentence,
                theme=theme,
                horizon=infer_horizon(sentence),
                direction=direction,
                assets=assets,
                catalysts=infer_catalysts(sentence),
                risks=risks_in_doc,
                implied_positioning=infer_positioning(direction, assets, theme),
                confidence=confidence,
                freshness_score=0.8,
                status=ThesisStatus.active,
                source_ids=[source_id],
                evidence=[
                    Evidence(
                        document_id=document_id,
                        source_id=source_id,
                        excerpt=sentence,
                        published_at=published_at,
                        url=url,
                    )
                ],
            )
            theses.append(thesis)
        return deduplicate_theses(theses)


# ---------------------------------------------------------------------------
# Sentence / direction / asset inference
# ---------------------------------------------------------------------------

# Negations that flip polarity when near a marker (within ~4 tokens).
NEGATIONS = ("not ", "no longer", "isn't", "isn", "aren't", "aren", "won't",
             "will not", "never", "stop ", "stopping", "fails to")

_SENTENCE_SPLITTER = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def split_sentences(text: str) -> list[str]:
    chunks = _SENTENCE_SPLITTER.split(text)
    out: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or len(chunk) < 8:
            continue
        out.append(chunk)
    return out


def _count_markers(lowered: str, markers: tuple[str, ...]) -> int:
    """Count marker occurrences, discounting ones immediately preceded by a negation."""
    count = 0
    for marker in markers:
        idx = 0
        while True:
            pos = lowered.find(marker, idx)
            if pos < 0:
                break
            window = lowered[max(0, pos - 24):pos]
            if not any(neg in window for neg in NEGATIONS):
                count += 1
            idx = pos + len(marker)
    return count


def infer_direction(sentence: str) -> ViewDirection | None:
    lowered = sentence.lower()
    bullish = _count_markers(lowered, BULLISH_MARKERS)
    bearish = _count_markers(lowered, BEARISH_MARKERS)

    # "Watch / monitor / tactical" without directional markers -> watchful
    if bullish == 0 and bearish == 0:
        if any(w in lowered for w in ("watch ", "monitor", "tactical", "stay nimble")):
            return ViewDirection.watchful
        return None
    if bullish and bearish:
        # If they're close (mixed view) call it mixed; otherwise lean stronger
        if abs(bullish - bearish) <= 0:
            return ViewDirection.mixed
        return ViewDirection.bullish if bullish > bearish else ViewDirection.bearish
    if bullish:
        return ViewDirection.bullish
    return ViewDirection.bearish


def infer_assets(sentence: str) -> list[str]:
    lowered = sentence.lower()
    results: set[str] = set()
    for keyword, asset in ASSET_KEYWORDS.items():
        if keyword in lowered:
            results.add(asset)
    return sorted(results)


def infer_theme(sentence: str, assets: Iterable[str]) -> str:
    lowered = sentence.lower()
    # Prefer macro theme label if present (more useful than list of assets)
    for keyword, theme in THEME_KEYWORDS.items():
        if keyword in lowered:
            return theme
    asset_list = list(assets)
    if asset_list:
        return asset_list[0]  # single canonical theme for grouping
    return "macro"


def infer_horizon(sentence: str) -> str:
    for pattern, label in HORIZON_PATTERNS:
        match = pattern.search(sentence)
        if match:
            if label != "explicit":
                return label
            # reconstruct from groups
            return match.group(0).lower().strip()
    lowered = sentence.lower()
    if "weeks" in lowered:
        return "2-8 weeks"
    if "months" in lowered:
        return "1-6 months"
    if "quarter" in lowered:
        return "1-3 months"
    if "year" in lowered:
        return "6-18 months"
    return "2-12 weeks"


def infer_catalysts(sentence: str) -> list[str]:
    lowered = sentence.lower()
    for marker in CATALYST_PREFIXES:
        idx = lowered.find(marker)
        if idx >= 0:
            # take the tail clause after the catalyst marker
            tail = sentence[idx:].strip()
            # cut at sentence end
            tail = re.split(r"[.!?]", tail)[0].strip()
            if tail:
                return [tail]
    return []


def infer_risks(sentences: list[str]) -> list[str]:
    risks: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(marker in lowered for marker in RISK_MARKERS):
            risks.append(sentence.strip())
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for item in risks:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out[:3]


def infer_positioning(direction: ViewDirection, assets: list[str], theme: str) -> list[str]:
    if not assets:
        label = theme if theme != "macro" else "this theme"
        if direction == ViewDirection.bullish:
            return [f"Look for long expressions tied to {label} once an instrument is identified."]
        if direction == ViewDirection.bearish:
            return [f"Look for short / hedge expressions tied to {label}."]
        return [f"Monitor {label} for a cleaner cross-asset expression."]
    if direction == ViewDirection.bullish:
        return [f"Consider tactical long exposure in {asset}." for asset in assets]
    if direction == ViewDirection.bearish:
        return [f"Reduce or hedge exposure in {asset}." for asset in assets]
    if direction == ViewDirection.mixed:
        return [f"Keep positioning balanced in {asset} until conviction improves." for asset in assets]
    return [f"Watch {asset} for confirmation before adding exposure." for asset in assets]


def infer_confidence(sentence: str, assets: list[str]) -> float:
    lowered = sentence.lower()
    score = 0.40
    if assets:
        score += 0.12
    if any(marker in lowered for marker in CONVICTION_MARKERS):
        score += 0.18
    if any(marker in lowered for marker in HEDGING_MARKERS):
        score -= 0.10
    if "risk" in lowered:
        score += 0.03  # author is acknowledging risk, not a ding
    if len(sentence) < 60:
        score -= 0.05  # very short clauses rarely contain a full thesis
    return max(0.05, min(score, 0.92))


def thesis_id_for(document_id: str, sentence: str) -> str:
    return hashlib.sha1(f"{document_id}|{sentence}".encode("utf-8")).hexdigest()[:16]


def deduplicate_theses(theses: list[Thesis]) -> list[Thesis]:
    seen: set[str] = set()
    deduped: list[Thesis] = []
    for thesis in theses:
        key = thesis.thesis.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(thesis)
    return deduped
