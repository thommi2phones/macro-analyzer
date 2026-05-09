"""Heuristic-only text parsing for manual drops.

Piece 1 scope: extract simple cues from the blurb so the SPA can pre-fill
metadata. NO LLM call. The rich vendored `chat_analyzer.py` (Claude-backed
extraction of structured trades from full chat exports) lives at
`vendor/trading_agent/analysis/chat_history/chat_analyzer.py` and will be
ported in a later session if/when bulk export ingestion is wanted.
"""

from __future__ import annotations

import re

# Match LONG/SHORT/WATCH and common synonyms anywhere in the blurb.
_SIDE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("LONG", re.compile(r"\b(long|buy|bullish|breakout|reclaim)\b", re.I)),
    ("SHORT", re.compile(r"\b(short|sell|bearish|breakdown|fade)\b", re.I)),
    ("WATCH", re.compile(r"\b(watch|watching|setup forming|on radar)\b", re.I)),
]

# 1H / 4H / 1D / 1W with optional space, also common phrasings.
_TF_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("1H", re.compile(r"\b(1\s*h|1\s*hour|hourly)\b", re.I)),
    ("4H", re.compile(r"\b(4\s*h|4\s*hour)\b", re.I)),
    ("1D", re.compile(r"\b(1\s*d|daily|1\s*day)\b", re.I)),
    ("1W", re.compile(r"\b(1\s*w|weekly|1\s*week)\b", re.I)),
]


def detect_side(text: str) -> str | None:
    """Return LONG / SHORT / WATCH, or None if nothing obvious."""
    if not text:
        return None
    for label, pat in _SIDE_PATTERNS:
        if pat.search(text):
            return label
    return None


def detect_timeframe(text: str) -> str | None:
    if not text:
        return None
    for label, pat in _TF_PATTERNS:
        if pat.search(text):
            return label
    return None


def extract_first_line(text: str, max_len: int = 120) -> str:
    """First non-empty line, trimmed — good fit for the auto-suggested note."""
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:max_len]
    return ""
