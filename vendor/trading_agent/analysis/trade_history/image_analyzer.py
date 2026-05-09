"""
Trade history image analyzer.

Uses Claude's vision API (claude-opus-4-6 with adaptive thinking) to extract
structured trade data from screenshots – ThinkorSwim trade confirmations,
chart annotations, brokerage statements, etc.

Usage:
    analyzer = ImageTradeAnalyzer(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Single image
    record = analyzer.analyze_image("./trade_images/aapl_long.png")

    # Entire folder
    records = analyzer.analyze_directory("./trade_images")
"""

import base64
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MEDIA_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}

# ── Data model ────────────────────────────────────────────────────────────────

class TradeRecord(BaseModel):
    """Structured trade data extracted from a screenshot."""

    # ── Core trade fields ─────────────────────────────────────────────────────
    ticker: str
    direction: str                              # "long" | "short"
    entry_price: Optional[float] = None        # WHITE horizontal ray
    exit_price: Optional[float] = None         # ORANGE horizontal ray (TP)
    stop_loss: Optional[float] = None          # stop loss level if marked
    entry_date: Optional[str] = None           # YYYY-MM-DD
    exit_date: Optional[str] = None
    pnl_dollars: Optional[float] = None
    pnl_percent: Optional[float] = None        # % from entry to TP

    # ── Chart structure ───────────────────────────────────────────────────────
    timeframe: Optional[str] = None            # "1m","15m","1h","4h","1D","1W"
    setup_type: Optional[str] = None           # "falling wedge", "cup and handle", etc.
    fib_levels: Optional[dict] = None          # {"0.618": {"price": 159.65, "color": "green"}}
    key_levels: list[float] = Field(default_factory=list)   # blue dashed line prices
    indicators_visible: list[str] = Field(default_factory=list)

    # ── Momentum + confluence ─────────────────────────────────────────────────
    macd_state: Optional[str] = None           # "bullish_expanding","bearish_expanding","squeeze","neutral"
    rsi_state: Optional[str] = None            # "above_50","below_50","bullish_divergence", etc.
    confluence_score: Optional[int] = None     # 1–5 aligned factors
    bias: Optional[str] = None                 # "bullish" | "bearish" | "neutral"
    invalidation_level: Optional[float] = None # price that breaks the thesis

    # ── Outcome + meta ────────────────────────────────────────────────────────
    win: Optional[bool] = None                 # True=hit TP, False=stopped, None=unknown
    reviewed: bool = False                     # human-reviewed via review_trades.py
    notes: Optional[str] = None
    image_path: Optional[str] = None
    extracted_at: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )

    @field_validator("direction")
    @classmethod
    def normalize_direction(cls, v: str) -> str:
        v = v.lower().strip()
        if v in ("long", "buy", "bullish"):
            return "long"
        if v in ("short", "sell", "bearish"):
            return "short"
        return v

    @field_validator("bias")
    @classmethod
    def normalize_bias(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.lower().strip()
        if v in ("bullish", "bull", "long"):
            return "bullish"
        if v in ("bearish", "bear", "short"):
            return "bearish"
        return "neutral"


# ── Extraction prompt ─────────────────────────────────────────────────────────

_PROMPT = """\
You are analyzing a TradingView chart screenshot for a professional swing trader.
Use the full analysis framework below — evaluate in priority order.

════════════════════════════════════════════════════════════
CHART MARKUP CONVENTIONS (owner-specific, read first)
════════════════════════════════════════════════════════════
  • WHITE horizontal rays    = ENTRY price (long or short)
  • ORANGE horizontal rays   = TAKE PROFIT (TP) price
  • RED horizontal rays      = STOP LOSS — NEVER confuse with entry or TP
  • BLUE dashed horizontals  = Key historical S/R levels (NOT entry/TP/SL)
  • BLUE solid lines         = Pattern structures (channels, wedges, trend lines)
  • Direction: TP < entry → SHORT | TP > entry → LONG
  • Multiple WHITE rays      = Multiple entries (can be both long AND short on same chart)
  • RED ray near entries     = Stop loss — group by proximity to determine which entry it covers

════════════════════════════════════════════════════════════
ANALYSIS PRIORITY HIERARCHY
════════════════════════════════════════════════════════════

PRIORITY 1 — PATTERN (most important)
  Patterns drawn with solid blue lines. Valid pattern requires:
  - Clear geometric structure
  - Multiple reaction points
  - Respect of boundaries
  Types: flag, pennant, rising/falling channel, wedge, H&S, inverse H&S,
         cup and handle, symmetrical triangle, descending channel

PRIORITY 2 — FIBONACCI CONFLUENCE
  Anchored swing to swing. Color significance:
  - WHITE fib level  = normal
  - YELLOW fib level = important
  - GREEN fib level  = critical (highest probability reaction)
  Retracements: 0.382, 0.5, 0.618, 0.65–0.70, 0.786
  Extensions: 1.272, 1.414, 1.618, 2.0
  Rule: Green fib inside pattern = highest probability zone
        Yellow fib at pattern support = strong entry zone
        Fib alone does NOT create a trade

PRIORITY 3 — BLUE DASHED HISTORICAL LEVELS
  Major historical support/resistance, prior breakout zones, multi-touch levels
  Confluence: pattern + fib + blue dashed level = strong structural zone

PRIORITY 4 — MACD + TTM SQUEEZE (primary momentum)
  Bullish: increasing positive histogram, squeeze release upward
  Bearish: increasing negative histogram, squeeze release downward
  Divergence: weakening histogram vs new price high = caution

PRIORITY 5 — RSI STRUCTURE (secondary confirmation)
  Used structurally — NOT overbought/oversold
  Bullish: holding above 50, bullish divergence at support
  Bearish: holding below 50, bearish divergence at resistance
  Also check: RSI trend line breaks, RSI H&S formations

PRIORITY 6 — EMA CLUSTER (Thanos)
  Tight compression = volatility expansion coming
  Strong stacking = trend strength
  Not primary signal — confluence only

PRIORITY 7 — SRCHANNEL
  Structural gut check. If aligns with pattern + fib + dashed level → zone matters more

════════════════════════════════════════════════════════════
CONFLUENCE SCORING
════════════════════════════════════════════════════════════
  5/5 = Extremely high probability
  4/5 = High
  3/5 = Medium
  2/5 = Low — wait for more confluence
  Factors: pattern + fib color + dashed level + MACD + RSI

════════════════════════════════════════════════════════════
EXTRACTION TASK
════════════════════════════════════════════════════════════
  1. WHITE ray price → entry_price
  2. ORANGE ray price → exit_price (TP)
  3. Ticker from header
  4. Timeframe from header
  5. Primary pattern (blue solid lines)
  6. Fib levels with colors
  7. Blue dashed price levels
  8. MACD + TTM state
  9. RSI structure
  10. Direction (long if TP > entry, short if TP < entry)

Return ONLY a valid JSON object – no markdown, no explanation:

{
  "ticker":              string – symbol as shown (e.g. "XAGUSD", "BTCUSDT", "SOL/USD"),
  "direction":           "long" or "short",
  "entry_price":         number – WHITE horizontal ray price (null if not present),
  "exit_price":          number – ORANGE horizontal ray / TP price (null if not present),
  "stop_loss":           number – stop loss level if marked, or null,
  "entry_date":          "YYYY-MM-DD" or null,
  "exit_date":           "YYYY-MM-DD" or null,
  "pnl_dollars":         number or null,
  "pnl_percent":         number – % move from entry to TP (negative for losses) or null,
  "timeframe":           string – exactly as shown e.g. "1m","15m","1h","4h","1D","1W",
  "setup_type":          string – primary pattern e.g. "falling wedge","cup and handle",
                                  "descending channel","symmetrical triangle","breakout",
                                  "bull flag","H&S","inverse H&S","Fibonacci retracement",
  "fib_levels":          object – visible fib prices with color e.g.
                                  {"0.618": {"price": 159.65, "color": "green"},
                                   "0.786": {"price": 116.0, "color": "white"}}
                                  or null if no fib tool visible,
  "key_levels":          array – prices from BLUE dashed lines e.g. [105.06, 81.94] or [],
  "indicators_visible":  array – indicator names e.g. ["MACD","TTM Squeeze","RSI","EMA cluster"],
  "macd_state":          string – "bullish_expanding","bearish_expanding","squeeze","neutral" or null,
  "rsi_state":           string – "above_50","below_50","bullish_divergence","bearish_divergence",
                                  "trend_break" or null,
  "confluence_score":    number – 1 to 5 (count of aligned factors),
  "win":                 true if hit TP, false if stopped out, null if unknown,
  "bias":                "bullish" or "bearish" or "neutral",
  "invalidation_level":  number – price that breaks the trade thesis, or null,
  "notes":               string – concise setup description: pattern quality, key fib confluence,
                                  MACD/RSI state, most probable next move
}
"""


# ── Analyzer ──────────────────────────────────────────────────────────────────

class ImageTradeAnalyzer:

    def __init__(self, api_key: str, model: str = "claude-opus-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    # ── Public ────────────────────────────────────────────────────────────────

    def analyze_image(self, image_path: str) -> TradeRecord:
        """
        Analyze a single trade screenshot and return a structured TradeRecord.

        Raises:
            ValueError  – if the file is unsupported or Claude returns invalid JSON
            FileNotFoundError – if the file does not exist
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image format: {suffix}")

        media_type = MEDIA_TYPES[suffix]
        image_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

        raw_json = self._call_claude(image_b64, media_type)
        data = self._parse_json(raw_json)
        data["image_path"] = str(path.resolve())
        return TradeRecord(**data)

    def analyze_directory(
        self,
        directory: str,
        skip_names: set[str] | None = None,
        checkpoint_path: str | None = None,
        checkpoint_every: int = 10,
    ) -> list[TradeRecord]:
        """
        Analyze all trade screenshots in a directory.
        Skips files that fail gracefully and logs errors.
        Saves a checkpoint file every N images so crashes don't lose progress.

        Args:
            directory:        Path to folder containing images.
            skip_names:       Set of filenames (basename only) to skip.
            checkpoint_path:  Path to save incremental JSON checkpoint.
                              Defaults to <directory>/../data/checkpoint.json
            checkpoint_every: Save checkpoint every N successfully analyzed images.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        skip_names = skip_names or set()

        # ── Checkpoint path ───────────────────────────────────────────────────
        if checkpoint_path is None:
            checkpoint_path = str(dir_path.parent / "data" / "checkpoint.json")
        cp_path = Path(checkpoint_path)

        # ── Load existing checkpoint so we can resume mid-run ─────────────────
        checkpoint_records: list[dict] = []
        checkpoint_names: set[str] = set()
        if cp_path.exists():
            try:
                checkpoint_records = json.loads(cp_path.read_text())
                checkpoint_names = {
                    Path(r["image_path"]).name
                    for r in checkpoint_records
                    if r.get("image_path")
                }
                print(f"  📂 Checkpoint found: {len(checkpoint_records)} records already saved.")
                print(f"     Resuming from where we left off...\n")
            except Exception as e:
                logger.warning("Could not load checkpoint: %s", e)

        # Merge skip_names with checkpoint_names (don't re-process checkpointed images)
        all_skip = skip_names | checkpoint_names

        all_images = sorted(
            p for p in dir_path.iterdir()
            if p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        images = [p for p in all_images if p.name not in all_skip]

        if not all_images:
            logger.warning("No supported images found in %s", directory)
            return []

        skipped = len(all_images) - len(images)
        if skipped:
            print(f"  Skipping {skipped} already-processed images.\n")

        if not images:
            print("  All images already processed.")
            # Return checkpoint records as TradeRecord objects
            return [TradeRecord(**r) for r in checkpoint_records]

        # ── Process images ─────────────────────────────────────────────────────
        new_records: list[TradeRecord] = []
        for idx, img_path in enumerate(images, 1):
            total_done = len(checkpoint_records) + len(new_records)
            total_all  = len(all_images)
            print(
                f"  [{total_done + 1}/{total_all}] {img_path.name} ...",
                end=" ", flush=True
            )
            try:
                record = self.analyze_image(str(img_path))
                new_records.append(record)
                entry_str = f"entry={record.entry_price}" if record.entry_price else "entry=?"
                tp_str    = f"tp={record.exit_price}"    if record.exit_price    else "tp=?"
                win_label = (
                    "WIN ✓" if record.win is True
                    else "LOSS ✗" if record.win is False
                    else "?"
                )
                print(
                    f"{record.ticker} {record.direction.upper()} | "
                    f"{entry_str} | {tp_str} | "
                    f"{record.setup_type or 'unknown setup'} | {win_label}"
                )

                # ── Checkpoint every N images ──────────────────────────────────
                if len(new_records) % checkpoint_every == 0:
                    self._save_checkpoint(
                        cp_path, checkpoint_records, new_records
                    )
                    print(
                        f"  💾 Checkpoint saved "
                        f"({len(checkpoint_records) + len(new_records)}/{total_all} total)"
                    )

            except Exception as exc:
                logger.error("Failed to analyze %s: %s", img_path.name, exc)
                print(f"ERROR – {exc}")

        # ── Final checkpoint save ──────────────────────────────────────────────
        all_records = self._save_checkpoint(cp_path, checkpoint_records, new_records)
        print(f"\n  ✅ Complete. Checkpoint saved → {cp_path}")

        return all_records

    @staticmethod
    def _save_checkpoint(
        cp_path: Path,
        existing: list[dict],
        new_records: list["TradeRecord"],
    ) -> list["TradeRecord"]:
        """Merge existing checkpoint dicts with new TradeRecord objects and save."""
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        combined_dicts = existing + [r.model_dump() for r in new_records]
        cp_path.write_text(json.dumps(combined_dicts, indent=2, default=str))
        # Return as TradeRecord objects
        from pydantic import ValidationError
        result = []
        for d in combined_dicts:
            try:
                result.append(TradeRecord(**d))
            except ValidationError:
                pass
        return result

    # ── Private ───────────────────────────────────────────────────────────────

    def _call_claude(self, image_b64: str, media_type: str) -> str:
        """Send image to Claude and return raw text response."""
        with self._client.messages.stream(
            model=self._model,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        ) as stream:
            response = stream.get_final_message()

        # Pull text blocks only (skip thinking blocks)
        texts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(texts).strip()

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """
        Extract JSON from Claude's response.
        Handles cases where the model wraps JSON in markdown code fences.
        """
        # Strip markdown code fences if present
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fence_match:
            raw = fence_match.group(1).strip()

        # Try to find the outermost JSON object
        brace_match = re.search(r"\{[\s\S]*\}", raw)
        if brace_match:
            raw = brace_match.group(0)

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Claude returned invalid JSON: {exc}\n\nRaw output:\n{raw}") from exc
