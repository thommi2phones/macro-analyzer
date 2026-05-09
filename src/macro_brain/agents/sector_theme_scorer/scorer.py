"""Sector Theme Strength — heuristic, no LLM.

Reads `setup.theme_signals` (preloaded by the scoring runner) and
emits a SubScore for `sector_theme_strength`.

Shape of theme_signals:
  {
    "theme_signals": {theme_key: weighted_mention_score, ...},
    "asset_themes": [theme_key, ...],     # themes THIS ticker belongs to
    "scale": float,                        # 75th-pct score across themes
  }

Logic: among the ticker's themes, take the strongest weighted mention
score; normalize by `scale` (75th percentile of theme scores in the
current pass). Output via tanh so heavy tails compress.
  - No themes for ticker → 0.5
  - All theme scores zero → 0.5
"""

from __future__ import annotations

import math

from macro_brain.agents._heuristic_log import with_log
from macro_brain.types import SetupContext, SubScore

VERSION = "sector_theme_strength@v1"


def _compute(payload: dict) -> SubScore:
    signals: dict = payload.get("theme_signals") or {}
    asset_themes: list = payload.get("asset_themes") or []
    scale = payload.get("scale") or 0.0

    if not asset_themes:
        return SubScore(
            component="sector_theme_strength",
            value=0.5,
            contributing_features={"n_themes": 0.0},
            notes="Ticker not mapped to any theme.",
        )

    theme_scores = [(t, float(signals.get(t, 0.0))) for t in asset_themes]
    best_theme, best_score = max(theme_scores, key=lambda kv: kv[1])

    if scale <= 0 or best_score <= 0:
        return SubScore(
            component="sector_theme_strength",
            value=0.5,
            contributing_features={
                "n_themes": float(len(asset_themes)),
                "best_score": float(best_score),
                "scale": float(scale),
            },
            notes=f"Theme '{best_theme}' has no mention activity this window.",
        )

    normalized = best_score / scale
    value = math.tanh(normalized)
    value = max(0.0, min(1.0, value))

    return SubScore(
        component="sector_theme_strength",
        value=value,
        contributing_features={
            "n_themes": float(len(asset_themes)),
            "best_score": float(best_score),
            "scale": float(scale),
            "normalized": float(normalized),
        },
        notes=f"Strongest theme '{best_theme}' score {best_score:.2f} (scale {scale:.2f}).",
    )


def score_sector_theme_strength(setup: SetupContext) -> SubScore:
    payload = setup.theme_signals or {}
    return with_log(
        agent_name="sector_theme_strength",
        version=VERSION,
        input_features=payload,
        fn=lambda: _compute(payload),
    )
