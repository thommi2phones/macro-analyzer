"""On-device OCR fast-path for chart screenshot headers.

Runs tesseract (via pytesseract) over uploaded images at /preview time and
regex-extracts the two screenshot formats the user routinely drops:

  1. Telegram screenshot — "Forwarded from: <emoji> <Group Name>" header.
     Yields channel + channel_type=telegram.

  2. TradingView screenshot — "<author> created with TradingView.com,
     <Mon DD, YYYY HH:MM UTC±N>" overlay in the chart's top-left, plus
     "<TICKER>/<QUOTE> ·  <TIMEFRAME> · <EXCHANGE>" near the symbol.
     Yields author + published_at + ticker + timeframe.

Returns a partial suggestions dict — never raises on OCR errors. Missing
fields stay None so the user-supplied values win on merge.

Why heuristic-only (no LLM): the auto-fill value is in overlay TEXT, not
chart structure. Gemini multimodal is reserved for Piece 2 (key levels,
bias, setup classification) once a public URL exists for image fetching.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Optional dep: pytesseract + Pillow. Heuristic gracefully no-ops if either
# is missing, so the app keeps running even if the user hasn't installed
# `brew install tesseract`.
try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
    _OCR_READY = True
except Exception as e:  # pragma: no cover - import-time only
    pytesseract = None  # type: ignore
    Image = None  # type: ignore
    _OCR_READY = False
    logger.info("OCR fast-path disabled (pytesseract/Pillow unavailable): %s", e)


# ── Result shape ─────────────────────────────────────────────────────────────


@dataclass
class OcrSuggestions:
    """Partial auto-fill suggestions from one image's overlay text.

    All fields nullable. Caller merges across images, then merges with
    user-supplied form values (user wins).
    """

    channel: Optional[str] = None
    channel_type: Optional[str] = None  # telegram | tradingview | other
    author: Optional[str] = None
    ticker: Optional[str] = None
    timeframe: Optional[str] = None  # 1H | 4H | 1D | 1W (normalized)
    published_at: Optional[str] = None  # ISO 8601
    detected_format: Optional[str] = None  # telegram_forward | tradingview_chart | unknown
    raw_text: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "channel_type": self.channel_type,
            "author": self.author,
            "ticker": self.ticker,
            "timeframe": self.timeframe,
            "published_at": self.published_at,
            "detected_format": self.detected_format,
            "notes": list(self.notes),
        }


# ── Format detectors / extractors ────────────────────────────────────────────


# "Forwarded from: 🪶 Feather Hands Trading"
# Tesseract sometimes drops the emoji or replaces it with garbage chars; the
# regex tolerates leading non-letter junk before the channel name.
_TG_FORWARD_RE = re.compile(
    r"Forwarded\s+from\s*[:\-]?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Strip leading emoji / non-letter noise that tesseract emits as `[]©™` etc.
_LEADING_NOISE_RE = re.compile(r"^[^\w@#]+")

# "Big_Nuts created with TradingView.com, May 08, 2026 18:00 UTC-7"
# (also: "User created with TradingView, May 08 2026 18:00 UTC-7")
_TV_HEADER_RE = re.compile(
    r"([A-Za-z0-9_\-\.]{2,})\s+created\s+with\s+TradingView(?:\.com)?,?\s*"
    r"([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}(?:\s+\d{1,2}:\d{2})?(?:\s+UTC[+\-]?\d{1,2})?)",
    re.IGNORECASE,
)

# Ticker near top: "SOL / TetherUS · 1D · Binance"  (·, •, |, or whitespace separators)
# Also tolerates: "SOLUSD 1D" or "BTCUSDT  4H"
_TV_SYMBOL_RE = re.compile(
    r"\b([A-Z]{2,10})\s*/\s*([A-Za-z]{2,10})\b",
)
# Standalone timeframe near top: "· 1D" "• 4H" or just "1D"
_TIMEFRAME_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,3}[mhMH]|1[DdWwMm]|[1-9]\d?[DdWwMm])(?![A-Za-z0-9])",
)


def _normalize_timeframe(raw: str) -> Optional[str]:
    """Map OCR'd timeframe tokens to the canonical 1H/4H/1D/1W set."""
    s = raw.strip().upper().replace(" ", "")
    # Only the canonical four are accepted; anything else (1m, 15m, 1M monthly)
    # is dropped because the SPA's pill row only has those four buttons.
    if s in ("1H", "4H", "1D", "1W"):
        return s
    # Common alternates
    if s in ("60", "60M"):
        return "1H"
    if s in ("240", "240M"):
        return "4H"
    if s in ("D", "DAY", "DAILY"):
        return "1D"
    if s in ("W", "WEEK", "WEEKLY"):
        return "1W"
    return None


def _parse_tv_datetime(raw: str) -> Optional[str]:
    """Best-effort parse of TradingView's overlay timestamp into ISO 8601.

    TV shows things like "May 08, 2026 18:00 UTC-7". We strip the UTC offset
    suffix (we don't carry a tz lib) and emit a naive ISO string the caller
    can store as `published_at`. Accuracy here is informational, not auditable
    — the user can correct it on the form.
    """
    s = raw.strip()
    # Drop trailing "UTC-7" / "UTC+0" — datetime.strptime with %Z is unreliable
    s = re.sub(r"\s*UTC[+\-]?\d{1,2}\s*$", "", s).strip()
    s = s.rstrip(",")
    fmts = [
        "%b %d, %Y %H:%M",
        "%b %d %Y %H:%M",
        "%b %d, %Y",
        "%b %d %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


def _extract_telegram(text: str, out: OcrSuggestions) -> bool:
    """Look for a 'Forwarded from: <channel>' line. Returns True on hit."""
    m = _TG_FORWARD_RE.search(text)
    if not m:
        return False
    raw = m.group(1).strip()
    raw = _LEADING_NOISE_RE.sub("", raw).strip()
    # Tesseract sometimes appends a `>` or `>>` — strip end punctuation
    raw = raw.rstrip(">»›").strip()
    if not raw:
        return False
    out.channel = raw
    out.channel_type = "telegram"
    out.detected_format = "telegram_forward"
    out.notes.append("channel from Telegram 'Forwarded from' header")
    return True


# Common tesseract misreads of TradingView usernames → canonical names.
# Add here as new patterns surface in the wild (e.g. "Nuts" from cropped
# "Big_Nuts", "ig_Nuts" from a different crop, etc.).
_AUTHOR_ALIASES: dict[str, str] = {
    "nuts": "Big_Nuts",
    "ig_nuts": "Big_Nuts",
    "ig_Nuts": "Big_Nuts",
    "big_nuts": "Big_Nuts",
    "BigNuts": "Big_Nuts",
    # joejoe55 — common tesseract misreads of the leading "j" or "5" digits.
    "joejoe": "joejoe55",
    "joejoes5": "joejoe55",
    "ioejoe55": "joejoe55",
    "joe_joe55": "joejoe55",
    "Joejoe55": "joejoe55",
    "JoeJoe55": "joejoe55",
}


def _canonicalize_author(raw: str) -> str:
    """Map fuzzy OCR'd author names to their canonical form."""
    key = raw.strip()
    if key in _AUTHOR_ALIASES:
        return _AUTHOR_ALIASES[key]
    if key.lower() in _AUTHOR_ALIASES:
        return _AUTHOR_ALIASES[key.lower()]
    return key


def _extract_tradingview(text: str, out: OcrSuggestions) -> bool:
    """Look for TradingView header + symbol + timeframe. Returns True on any hit."""
    hit = False

    m = _TV_HEADER_RE.search(text)
    if m:
        author = _canonicalize_author(m.group(1).strip().rstrip(".:,"))
        date_raw = m.group(2).strip()
        out.author = author
        # TradingView is the *charting platform*, not a delivery venue.
        # We surface the author but leave channel_type for the user to set
        # (or for the seed author's default to take over).
        out.channel = "self" if author.lower() in ("self", "me") else author
        out.detected_format = "tradingview_chart"
        out.notes.append(f"author '{author}' from TradingView header")
        iso = _parse_tv_datetime(date_raw)
        if iso:
            out.published_at = iso
            out.notes.append(f"timestamp parsed: {iso}")
        else:
            out.notes.append(f"timestamp seen but unparsed: '{date_raw}'")
        hit = True

    # Symbol — look in the top portion of the OCR text (TV puts it near the
    # very first lines). Take the first match.
    head = "\n".join(text.splitlines()[:8])
    sm = _TV_SYMBOL_RE.search(head)
    if sm:
        out.ticker = sm.group(1)
        out.notes.append(f"ticker '{out.ticker}' from symbol pair {sm.group(0)}")
        hit = True

    # Timeframe — only the canonical four; first valid hit in the head wins.
    for tf_match in _TIMEFRAME_RE.finditer(head):
        tf = _normalize_timeframe(tf_match.group(1))
        if tf:
            out.timeframe = tf
            out.notes.append(f"timeframe '{tf}' from token '{tf_match.group(1)}'")
            break

    return hit


# ── Public API ───────────────────────────────────────────────────────────────


def is_available() -> bool:
    """True when OCR can actually run (deps present)."""
    return _OCR_READY


def analyze_image(image_path: str | Path) -> OcrSuggestions:
    """Run OCR + heuristic regex on a single chart screenshot.

    Never raises — on any failure returns an empty `OcrSuggestions`. The
    caller merges across multiple images and then with user form values.
    """
    out = OcrSuggestions()
    if not _OCR_READY:
        out.notes.append("OCR deps unavailable; skipped")
        return out
    p = Path(image_path)
    if not p.exists():
        out.notes.append(f"image not found: {p}")
        return out
    try:
        with Image.open(p) as img:
            # Preserve resolution — TV/TG overlays are small and benefit
            # from full-res. Tesseract handles RGBA fine.
            text = pytesseract.image_to_string(img, lang="eng")
    except Exception as e:
        logger.warning("OCR failed for %s: %s", p, e)
        out.notes.append(f"OCR error: {e}")
        return out

    out.raw_text = text
    if _extract_telegram(text, out):
        return out
    if _extract_tradingview(text, out):
        return out
    out.detected_format = "unknown"
    out.notes.append("no recognized overlay format matched")
    return out


def analyze_images(image_paths: list[str | Path]) -> OcrSuggestions:
    """Run OCR over each image, merge into one suggestions object.

    Merge rule: first non-null wins. Order matches the user's drop order,
    so the first attached image takes precedence — typical when the first
    drop is the source-of-truth chart and later drops are supporting views.
    """
    merged = OcrSuggestions()
    for path in image_paths:
        sug = analyze_image(path)
        format_known = bool(sug.detected_format and sug.detected_format != "unknown")
        if format_known:
            merged.notes.append(f"[{Path(path).name}] {sug.detected_format}")
            # First image with a recognized format sets the merged format.
            # Later recognized formats are recorded in notes but don't override.
            if not merged.detected_format or merged.detected_format == "unknown":
                merged.detected_format = sug.detected_format
        for fld in ("channel", "channel_type", "author", "ticker",
                    "timeframe", "published_at"):
            cur = getattr(merged, fld)
            new = getattr(sug, fld)
            if cur is None and new is not None:
                setattr(merged, fld, new)
        merged.notes.extend(f"  · {n}" for n in sug.notes)
    if not merged.detected_format:
        # Single-image with one clean format and no other inputs falls
        # through here too — surface "unknown" only when no image matched.
        merged.detected_format = "unknown"
    return merged
