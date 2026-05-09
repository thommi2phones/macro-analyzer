"""Pre-tagger: lightweight keyword routing of documents to production agents.

NO LLM CALLS. By design. The whole point is to decide which production
agents care about a document BEFORE we spend on LLM inference.

Two inputs:
1. The document's content + title + source's routing_tags
2. config/source_routing.json (tag → list of agents)

Output: set of agent names that should process this document.

If a document yields zero agents, it's logged as skipped — there's no
useful work for the brain to do on it. Surfaces in the source health
panel as a noise indicator (high skip rate = source isn't earning its
keep).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from macro_positioning.core.settings import settings


ROUTING_PATH = settings.base_dir / "config" / "source_routing.json"


# ---------------------------------------------------------------------------
# Keyword inventory — the substrings that promote a tag from "unknown" to
# "present in document". Multi-word triggers use whole-phrase match. Single
# tokens use word-boundary regex to avoid false positives ("rates" should
# match "rates" but not "berates").
# ---------------------------------------------------------------------------

# Tag → list of (lowercase) trigger keywords/phrases.
# Order doesn't matter; first match per tag is enough.
TAG_TRIGGERS: dict[str, list[str]] = {
    "macro": ["macro", "macroeconomic", "regime", "cycle"],
    "rates": ["rate", "rates", "yield", "yields", "treasury", "treasuries", "bond", "duration"],
    "inflation": ["inflation", "cpi", "ppi", "pce", "deflation", "disinflation", "stagflation"],
    "growth": ["gdp", "growth", "recession", "expansion", "contraction"],
    "labor": ["labor", "employment", "unemployment", "jobs", "payroll", "nfp", "jobless"],
    "credit": ["credit", "spread", "default", "delinquency", "high yield", "investment grade"],
    "liquidity": ["liquidity", "balance sheet", "qe", "qt", "tga", "rrp", "reserves", "stablecoin"],
    "fx": ["dollar", "dxy", "currency", "fx", "yen", "euro", "yuan"],
    "geopolitics": ["war", "conflict", "sanctions", "geopolitic", "geopolitical", "ukraine", "russia", "china", "iran", "israel", "taiwan"],
    "fed": ["fed", "powell", "fomc", "federal reserve", "central bank"],
    "equities": ["equities", "stocks", "spx", "s&p", "nasdaq", "russell", "earnings", "buyback"],
    "crypto": ["crypto", "bitcoin", "btc", "ethereum", "eth", "altcoin", "stablecoin", "defi"],
    "commodities": ["commodit", "wti", "brent", "gold", "silver", "copper", "oil", "natural gas", "uranium"],
    "energy": ["energy", "oil", "natural gas", "lng", "crude", "opec", "uranium", "nuclear", "grid", "power"],
    "ai": ["ai", "artificial intelligence", "llm", "machine learning", "gpu", "data center", "datacenter"],
    "tech": ["tech", "software", "semiconductor", "chip", "cloud"],
    "sentiment": ["sentiment", "fear", "greed", "vix", "positioning"],
    "headlines": ["breaking", "alert"],
    "chart": ["chart", "screenshot", "tradingview"],
    "technical": ["breakout", "support", "resistance", "moving average", "rsi", "macd", "trendline"],
    "vision": ["chart", "screenshot"],
    "podcast": ["podcast", "episode", "transcript"],
    "manual": ["my note", "user note", "manual entry"],
    "ticker_news": ["earnings", "guidance", "downgrade", "upgrade"],
    "high_priority": ["urgent", "high priority", "thomas note"],  # rarely auto-detected; usually source-tagged
}


# ---------------------------------------------------------------------------
# Routing config loader (cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_routing() -> dict:
    """Load config/source_routing.json. Cached for the process lifetime;
    bust with `clear_routing_cache()` after edits.
    """
    if not ROUTING_PATH.exists():
        return {"tag_to_agents": {}}
    return json.loads(ROUTING_PATH.read_text())


def clear_routing_cache() -> None:
    """Force the next `_load_routing()` to re-read from disk."""
    _load_routing.cache_clear()


# ---------------------------------------------------------------------------
# Tag detection
# ---------------------------------------------------------------------------

def detect_tags(text: str) -> set[str]:
    """Scan text for trigger keywords and return all matched tags.

    Case-insensitive. Multi-word triggers match as substrings; single-word
    triggers use word-boundary regex.
    """
    if not text:
        return set()
    lowered = text.lower()
    matched: set[str] = set()
    for tag, triggers in TAG_TRIGGERS.items():
        for kw in triggers:
            if " " in kw:
                # Multi-word: substring match is fine
                if kw in lowered:
                    matched.add(tag)
                    break
            else:
                # Single token: word boundary
                if re.search(rf"\b{re.escape(kw)}\b", lowered):
                    matched.add(tag)
                    break
    return matched


def merge_tags(
    detected_tags: set[str],
    source_routing_tags: list[str] | None = None,
) -> set[str]:
    """Combine tags detected in content with the source's preconfigured
    routing_tags from sources.json.

    Source-level tags are always trusted (they reflect human curation
    of the source's beat). Content-level tags add coverage when a
    source occasionally strays into adjacent topics.
    """
    out = set(detected_tags)
    if source_routing_tags:
        out.update(source_routing_tags)
    return out


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_to_agents(tags: set[str] | list[str]) -> set[str]:
    """Map a set of tags to the set of production agents that should
    process the document.

    Empty result means "no agent cares" — caller should log as skipped.
    """
    routing = _load_routing()
    tag_to_agents = routing.get("tag_to_agents", {})
    agents: set[str] = set()
    for tag in tags:
        for agent in tag_to_agents.get(tag, []):
            agents.add(agent)
    return agents


def route_document(
    text: str,
    *,
    title: str = "",
    source_routing_tags: list[str] | None = None,
) -> tuple[set[str], set[str]]:
    """One-shot: take a document's text/title + its source's routing_tags,
    return (matched_tags, agents_to_invoke).

    Caller decides what to do with the result:
    - If agents_to_invoke is empty → skip, log as routing-miss
    - Else → enqueue for each agent in the set
    """
    combined = f"{title}\n\n{text}" if title else text
    detected = detect_tags(combined)
    tags = merge_tags(detected, source_routing_tags)
    agents = route_to_agents(tags)
    return tags, agents
