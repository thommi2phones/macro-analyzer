"""End-to-end tests for the heuristic OCR fast-path.

Synthesizes two reference screenshots (Telegram forward header, TradingView
chart header) by drawing text onto a blank canvas, runs them through the
real pytesseract pipeline, and asserts the extracted fields. If tesseract
isn't installed on the dev box, the tests skip themselves instead of
failing — keeps CI green for contributors without the brew dep.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from macro_positioning.manual.heuristic_ocr import (
    analyze_image,
    analyze_images,
    is_available,
)


# Skip the entire module on machines without tesseract installed.
if not is_available() or shutil.which("tesseract") is None:
    pytest.skip("tesseract not installed on this host", allow_module_level=True)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402  (after skip check)


def _font(size: int) -> ImageFont.ImageFont:
    """Try a real font; fall back to PIL's default bitmap font if not found.

    Bitmap fonts at default size are tiny (~10px) — tesseract reads them
    well at 2x render. Real fonts give tesseract more to work with.
    """
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _render(text_lines: list[str], path: Path, width: int = 900, line_h: int = 36) -> None:
    """Draw light text on a dark background mimicking TG/TV chrome."""
    h = max(120, line_h * len(text_lines) + 40)
    img = Image.new("RGB", (width, h), color=(20, 20, 30))
    draw = ImageDraw.Draw(img)
    font = _font(24)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill=(230, 230, 240), font=font)
        y += line_h
    img.save(path)


def test_telegram_forward_header(tmp_path: Path):
    img = tmp_path / "tg.png"
    _render(
        [
            "Forwarded from: Feather Hands Trading",
            "SOL still in flagging channel could go test",
            "upper channel but still just wondering around",
        ],
        img,
    )
    sug = analyze_image(img)
    assert sug.detected_format == "telegram_forward"
    assert sug.channel_type == "telegram"
    # Tesseract OCR is fuzzy — assert the recognizable core of the channel.
    assert sug.channel is not None
    assert "Feather" in sug.channel or "feather" in sug.channel.lower()


def test_tradingview_header(tmp_path: Path):
    img = tmp_path / "tv.png"
    _render(
        [
            "Big_Nuts created with TradingView.com, May 08, 2026 18:00 UTC-7",
            "SOL / TetherUS  1D  Binance",
            "Open: 92.02  High: 92.62  Low: 91.85  Close: 92.47",
        ],
        img,
    )
    sug = analyze_image(img)
    # TV format detected; author present even if exact casing varies.
    # channel_type is intentionally NOT set from a TV chart — TradingView
    # is a charting platform, not a delivery venue.
    assert sug.detected_format == "tradingview_chart"
    assert sug.channel_type is None
    assert sug.author is not None
    assert "nuts" in sug.author.lower() or "big" in sug.author.lower()
    # Ticker extraction
    assert sug.ticker == "SOL"
    # Timeframe normalized to canonical 1D
    assert sug.timeframe == "1D"


def test_multi_image_merge_first_wins(tmp_path: Path):
    tg = tmp_path / "tg.png"
    tv = tmp_path / "tv.png"
    _render(["Forwarded from: Capo Crypto"], tg)
    _render(
        ["Big_Nuts created with TradingView.com, May 08, 2026 18:00 UTC-7",
         "BTC / USDT  4H"],
        tv,
    )
    # First image is TG → channel comes from it; second image fills TV
    # fields the first didn't set (ticker, timeframe, author).
    merged = analyze_images([tg, tv])
    assert merged.channel and "Capo" in merged.channel
    assert merged.channel_type == "telegram"  # first wins
    assert merged.author and "nuts" in merged.author.lower()
    assert merged.ticker == "BTC"
    assert merged.timeframe == "4H"


def test_unknown_format_returns_clean_empty(tmp_path: Path):
    img = tmp_path / "noise.png"
    _render(["Just some random sentence with no header.", "Another line."], img)
    sug = analyze_image(img)
    assert sug.detected_format in ("unknown", None)
    assert sug.channel is None
    assert sug.author is None


def test_missing_image_doesnt_raise(tmp_path: Path):
    sug = analyze_image(tmp_path / "no-such-file.png")
    assert sug.channel is None
    assert sug.detected_format is None or sug.detected_format == "unknown"
