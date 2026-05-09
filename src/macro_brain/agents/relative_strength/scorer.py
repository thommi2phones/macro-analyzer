"""Relative Strength — heuristic, no LLM.

Reads `setup.relative_strength_features` (preloaded by the scoring
runner) and emits a SubScore for `relative_strength`.

Shape:
  {
    "ticker_pct20d":     float | None,
    "benchmark_pct20d":  float | None,
    "benchmark_ticker":  str,
  }

Logic: ticker_20d_return − benchmark_20d_return; tanh-normalized via
a 10pp scale (so a 10pp outperformance ≈ 0.88, parity = 0.5, 10pp
underperformance ≈ 0.12).

Missing inputs → 0.5 with note.
"""

from __future__ import annotations

import math

from macro_brain.agents._heuristic_log import with_log
from macro_brain.types import SetupContext, SubScore

VERSION = "relative_strength@v1"
_SCALE = 0.10  # 10 percentage points → ~tanh(1.0) = 0.76


def _compute(feats: dict) -> SubScore:
    ticker_ret = feats.get("ticker_pct20d")
    bench_ret = feats.get("benchmark_pct20d")
    bench_ticker = feats.get("benchmark_ticker") or "?"

    if ticker_ret is None or bench_ret is None:
        return SubScore(
            component="relative_strength",
            value=0.5,
            contributing_features={"defined": 0.0},
            notes=f"Insufficient data vs benchmark {bench_ticker}.",
        )

    diff = float(ticker_ret) - float(bench_ret)
    value = 0.5 + 0.5 * math.tanh(diff / _SCALE)
    value = max(0.0, min(1.0, value))

    sign = "+" if diff >= 0 else ""
    return SubScore(
        component="relative_strength",
        value=value,
        contributing_features={
            "ticker_pct20d": float(ticker_ret),
            "benchmark_pct20d": float(bench_ret),
            "diff": float(diff),
        },
        notes=f"vs {bench_ticker}: {sign}{diff*100:.1f}pp 20d.",
    )


def score_relative_strength(setup: SetupContext) -> SubScore:
    feats = setup.relative_strength_features or {}
    return with_log(
        agent_name="relative_strength",
        version=VERSION,
        input_features=feats,
        fn=lambda: _compute(feats),
    )
