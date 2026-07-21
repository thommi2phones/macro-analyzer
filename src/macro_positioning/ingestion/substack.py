"""Substack RSS connector — operator-curated newsletter feed.

Every Substack publication exposes `{slug}.substack.com/feed` (or the
custom-domain equivalent at `{domain}/feed`). No API key, no auth.

Feeds are listed in `config/substack_feeds.json`:

  {
    "feeds": [
      {"slug": "doomberg", "url": "https://doomberg.substack.com/feed",
       "tags": ["energy", "macro"]},
      ...
    ]
  }

Each post becomes a document with `source_id=substack:{slug}` so the
data-health strip and signals layer can attribute it cleanly. The
LLM extractor handles the prose → signal step automatically; no
custom routing needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from macro_positioning.core.models import RawDocument
from macro_positioning.core.settings import settings
from macro_positioning.ingestion.rss_connector import fetch_feed, parse_feed

logger = logging.getLogger(__name__)


def _config_path() -> Path:
    return settings.base_dir / "config" / "substack_feeds.json"


def load_feeds() -> list[dict]:
    """Load the operator-curated Substack feed list.

    Returns an empty list if the config file is missing — the scheduler
    step then no-ops cleanly without raising. Operator adds feeds by
    editing the JSON file; no code change required.
    """
    path = _config_path()
    if not path.exists():
        logger.info("substack: %s not present, skipping", path)
        return []
    try:
        data = json.loads(path.read_text())
        return list(data.get("feeds") or [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("substack: failed to read %s: %s", path, exc)
        return []


def fetch_feed_entries(slug: str, url: str, max_items: int = 20,
                       extra_tags: list[str] | None = None) -> list[RawDocument]:
    """Pull one Substack RSS feed.

    `source_id` is namespaced `substack:{slug}` so downstream
    attribution (data_health, source leaderboard, signal provenance)
    can tell publications apart.
    """
    source_id = f"substack:{slug}"
    try:
        xml = fetch_feed(url)
    except Exception as exc:
        logger.warning("substack[%s] fetch failed: %s", slug, exc)
        return []
    docs = parse_feed(xml, source_id=source_id, max_items=max_items)

    tag_set = ["substack", slug]
    if extra_tags:
        tag_set.extend(t for t in extra_tags if t and t not in tag_set)

    for doc in docs:
        doc.tags = list(tag_set)
    logger.info("substack[%s] -> %d items", slug, len(docs))
    return docs


def fetch_all(max_items_per_feed: int = 20) -> list[RawDocument]:
    """Pull every configured Substack feed in one pass.

    Per-feed errors are logged but don't abort the run.
    """
    out: list[RawDocument] = []
    feeds = load_feeds()
    for f in feeds:
        slug = f.get("slug") or ""
        url = f.get("url") or ""
        if not slug or not url:
            logger.warning("substack: skipping malformed entry %s", f)
            continue
        try:
            out.extend(fetch_feed_entries(
                slug=slug, url=url,
                max_items=max_items_per_feed,
                extra_tags=f.get("tags") or [],
            ))
        except Exception as exc:
            logger.warning("substack[%s] entry failed: %s", slug, exc)
    return out
