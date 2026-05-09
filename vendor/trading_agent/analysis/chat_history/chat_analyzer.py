"""
Chat history analyzer.

Uses Claude to extract structured trade data from conversation logs —
ChatGPT exports, Claude exports, or any plain text chat transcripts
about trades, setups, and market analysis.

The extracted records feed directly into PatternLearner, giving you
the same pattern profile built from images, but from your written
trade discussions with AI models.

Supported input formats:
  • .txt   — raw conversation text (paste directly)
  • .md    — markdown-formatted chat exports
  • .json  — ChatGPT export format (conversations.json)
  • any text file with conversation content

Usage:
    analyzer = ChatAnalyzer(api_key=os.getenv("ANTHROPIC_API_KEY"))
    records  = analyzer.analyze_directory("./chat_exports")
    # or
    records  = analyzer.analyze_file("./chat_exports/trading_session.txt")
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

from analysis.trade_history.image_analyzer import TradeRecord

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".text"}

# ── Extraction prompt ─────────────────────────────────────────────────────────

_PROMPT = """\
You are analyzing a trading conversation between a trader and an AI assistant.

Your task: extract every distinct trade idea, trade analysis, or completed trade
discussed in this conversation.

For EACH trade found, create one entry in a JSON array:
[
  {
    "ticker":             string – the stock/crypto/futures ticker (e.g. "AAPL", "BTC/USD", "ES=F"),
    "direction":          "long" or "short",
    "entry_price":        number or null,
    "exit_price":         number or null,
    "entry_date":         "YYYY-MM-DD" or null,
    "exit_date":          "YYYY-MM-DD" or null,
    "pnl_dollars":        number (negative for loss) or null,
    "pnl_percent":        number (negative for loss) or null,
    "timeframe":          chart interval like "15m", "1h", "4h", "1d", "1wk" or null,
    "setup_type":         brief label e.g. "breakout", "bull flag", "pullback to EMA",
                          "VWAP reclaim", "earnings play", "macro trend" or null,
    "indicators_visible": array of indicators mentioned in the discussion
                          e.g. ["RSI", "MACD", "EMA 20", "VWAP", "Volume"] or [],
    "win":                true if trade was profitable, false if a loss, null if unknown/still open,
    "notes":              the trader's reasoning, thesis, key observations, and any
                          lessons learned mentioned in the conversation
  }
]

Rules:
- Only extract REAL trade ideas — skip hypothetical examples or generic explanations
- If a trade is discussed multiple times, create ONE entry with the most complete info
- If no trades are found, return an empty array: []
- Return ONLY valid JSON — no markdown, no explanation

CONVERSATION:
"""

# Max characters to send per Claude call (stay within context window)
_CHUNK_SIZE = 150_000


# ── ChatGPT export parser ─────────────────────────────────────────────────────

def _parse_chatgpt_json(raw: str) -> str:
    """
    Convert ChatGPT's conversations.json export to plain text.
    Handles both single conversation and array of conversations.
    """
    data = json.loads(raw)

    # Single conversation or list
    conversations = data if isinstance(data, list) else [data]

    chunks = []
    for conv in conversations:
        title = conv.get("title", "Conversation")
        chunks.append(f"\n=== {title} ===\n")

        mapping = conv.get("mapping", {})
        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            role    = msg.get("author", {}).get("role", "unknown")
            content = msg.get("content", {})

            # Content can be a dict with "parts" or a plain string
            if isinstance(content, dict):
                parts = content.get("parts", [])
                text  = " ".join(str(p) for p in parts if isinstance(p, str))
            else:
                text = str(content)

            if text.strip():
                chunks.append(f"[{role.upper()}]: {text}\n")

    return "\n".join(chunks)


# ── Analyzer ──────────────────────────────────────────────────────────────────

class ChatAnalyzer:

    def __init__(self, api_key: str, model: str = "claude-opus-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model  = model

    # ── Public ────────────────────────────────────────────────────────────────

    def analyze_text(self, text: str, source: str = "text") -> list[TradeRecord]:
        """
        Extract trade records from raw conversation text.
        Handles very long conversations by chunking.
        """
        if not text.strip():
            return []

        all_records: list[TradeRecord] = []

        # Split into chunks if the conversation is very long
        chunks = self._chunk_text(text)
        for i, chunk in enumerate(chunks):
            label = f"{source} (chunk {i+1}/{len(chunks)})" if len(chunks) > 1 else source
            logger.debug("Analyzing chunk %d/%d from %s", i + 1, len(chunks), source)
            records = self._extract_from_chunk(chunk, label)
            all_records.extend(records)

        # Deduplicate: same ticker + same entry_price → keep first
        return self._deduplicate(all_records)

    def analyze_file(self, path: str) -> list[TradeRecord]:
        """Analyze a single chat export file."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = file_path.suffix.lower()
        raw    = file_path.read_text(encoding="utf-8", errors="replace")

        # Handle ChatGPT JSON exports
        if suffix == ".json":
            try:
                text = _parse_chatgpt_json(raw)
            except Exception as exc:
                logger.warning("Could not parse as ChatGPT JSON, treating as plain text: %s", exc)
                text = raw
        else:
            text = raw

        return self.analyze_text(text, source=file_path.name)

    def analyze_directory(self, directory: str) -> list[TradeRecord]:
        """Analyze all chat export files in a directory."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

        files = sorted(
            p for p in dir_path.iterdir()
            if p.suffix.lower() in SUPPORTED_EXTENSIONS
        )

        if not files:
            logger.warning("No chat export files found in %s", directory)
            return []

        all_records: list[TradeRecord] = []
        for idx, file_path in enumerate(files, 1):
            print(f"  [{idx}/{len(files)}] {file_path.name} ...", end=" ", flush=True)
            try:
                records = self.analyze_file(str(file_path))
                all_records.extend(records)
                print(f"{len(records)} trades extracted")
            except Exception as exc:
                logger.error("Failed to analyze %s: %s", file_path.name, exc)
                print(f"ERROR – {exc}")

        return all_records

    # ── Private ───────────────────────────────────────────────────────────────

    def _extract_from_chunk(self, text: str, source: str) -> list[TradeRecord]:
        """Send a chunk to Claude and parse the response."""
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                messages=[
                    {
                        "role": "user",
                        "content": _PROMPT + text,
                    }
                ],
            ) as stream:
                response = stream.get_final_message()

            # Extract text blocks (skip thinking blocks)
            texts = [b.text for b in response.content if b.type == "text"]
            raw   = "\n".join(texts).strip()

            return self._parse_response(raw, source)

        except Exception as exc:
            logger.error("Claude extraction failed for %s: %s", source, exc)
            return []

    @staticmethod
    def _parse_response(raw: str, source: str) -> list[TradeRecord]:
        """Parse Claude's JSON response into TradeRecord objects."""
        # Strip markdown code fences
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fence:
            raw = fence.group(1).strip()

        # Find the JSON array
        array_match = re.search(r"\[[\s\S]*\]", raw)
        if array_match:
            raw = array_match.group(0)

        try:
            data_list = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error from %s: %s\nRaw: %s", source, exc, raw[:200])
            return []

        if not isinstance(data_list, list):
            return []

        records = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
            if not item.get("ticker"):
                continue
            try:
                item["extracted_at"] = datetime.now().isoformat()
                item["image_path"]   = None   # not applicable for chat
                records.append(TradeRecord(**item))
            except Exception as exc:
                logger.debug("Skipping malformed trade record: %s", exc)

        return records

    @staticmethod
    def _chunk_text(text: str, size: int = _CHUNK_SIZE) -> list[str]:
        """Split long text into chunks at paragraph boundaries."""
        if len(text) <= size:
            return [text]

        chunks, current = [], []
        current_len = 0

        for paragraph in text.split("\n\n"):
            if current_len + len(paragraph) > size and current:
                chunks.append("\n\n".join(current))
                current, current_len = [], 0
            current.append(paragraph)
            current_len += len(paragraph)

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    @staticmethod
    def _deduplicate(records: list[TradeRecord]) -> list[TradeRecord]:
        """Remove duplicate records (same ticker + entry_price)."""
        seen = set()
        unique = []
        for r in records:
            key = (r.ticker, r.entry_price, r.direction)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique
