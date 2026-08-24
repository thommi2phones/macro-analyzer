"""Twice-daily desk digest — the standing picture, not an interrupt.

The alert rules only speak when something *crosses*. That is deliberate,
and it means a quiet week is silent even though the desk still has a
ranked watchlist worth reading. This is the other half: three scheduled
drops with no threshold and no cooldown, sent after the 06:00 and 13:00
scoring passes.

Three separate messages rather than one, because they answer different
questions and get read at different depths:

  live signals — what the tracked voices just said
  hero signals — the top scored setups, with rails
  watchlist    — everything scored, ranked, grouped

Each is capped to Telegram's message limit independently, so a long
watchlist can never truncate the hero setups above it.
"""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_MAX = 3900          # headroom under Telegram's 4096

# The watchlist carries ~11 raw asset_class values; the desk thinks in
# three buckets, matching the SPA's split.
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CRYPTO", ("crypto",)),
    ("STOCKS & ETFs", ("equity", "commodity_equity", "commodity_and_equity",
                       "commodity_and_miners")),
    ("MACRO", ("commodity", "index", "bond", "currency", "cash_equivalent",
               "vol")),
)


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


def _now_line() -> str:
    return datetime.now().astimezone().strftime("%a %-d %b · %H:%M")


def _age(iso: str | None) -> str:
    """'2h' / '3d' — how long ago a signal landed."""
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    hours = (datetime.now(UTC) - then).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours / 24)}d"


def _side_dot(side: str | None) -> str:
    return {"LONG": "🟢", "SHORT": "🔴"}.get((side or "").upper(), "⚪️")


def _grade(score: int) -> str:
    from macro_brain.orchestrator.feature_vector import assign_grade
    return assign_grade(int(score or 0))


def _clip(lines: list[str], header: list[str]) -> str:
    """Join under the size cap, saying what was dropped rather than
    silently ending early."""
    out, budget = [], _MAX - len("\n".join(header)) - 1
    for i, line in enumerate(lines):
        remaining = len(lines) - i
        reserve = len(f"…and {remaining} more") + 1 if remaining > 1 else 0
        if budget - (len(line) + 1) < reserve:
            out.append(f"…and {remaining} more")
            break
        out.append(line)
        budget -= len(line) + 1
    return "\n".join(header + out)


def build_live_signals_message(rows: list[dict]) -> str | None:
    if not rows:
        return None
    header = [f"📡 <b>Live signals</b> · {len(rows)} freshest", _now_line(), ""]
    lines = []
    for r in rows:
        who = (r.get("author_id") or "").split(":")[-1] or "unknown"
        conv = r.get("conviction")
        bits = [f"{_side_dot(r.get('side'))} <b>{_esc(r.get('ticker'))}</b>",
                _esc(r.get("side"))]
        if conv is not None:
            bits.append(f"conv {conv:g}")
        bits.append(_esc(who))
        age = _age(r.get("extracted_at"))
        if age:
            bits.append(age)
        lines.append("  ".join(bits))
    return _clip(lines, header)


def build_hero_signals_message(rows: list[dict]) -> str | None:
    if not rows:
        return None
    header = [f"🎯 <b>Hero signals</b> · top {len(rows)} scored", _now_line(), ""]
    lines = []
    for i, r in enumerate(rows, 1):
        score = r.get("score") or 0
        lines.append(
            f"{i}. {_side_dot(r.get('side'))} <b>{_esc(r.get('asset'))}</b>  "
            f"{score}  {_grade(score)} · tier_{r.get('tier')}  "
            f"{_esc(r.get('side'))}"
        )
        if r.get("hasLevels") and r.get("entry"):
            rr = r.get("rr")
            lines.append(
                f"    entry {r['entry']:,.6g} · stop {r.get('stop', 0):,.6g} · "
                f"target {r.get('target', 0):,.6g}"
                + (f" · {rr:.1f}R" if isinstance(rr, (int, float)) else "")
            )
        if r.get("setup"):
            lines.append(f"    {_esc(r['setup'])}"
                         + ("" if r.get("levelStructural") else " (placeholder rails)"))
        lines.append("")
    return _clip(lines, header)


def build_watchlist_message(rows: list[dict]) -> str | None:
    if not rows:
        return None
    ranked = sorted(rows, key=lambda r: -(r.get("score") or 0))
    header = [f"📋 <b>Watchlist</b> · {len(ranked)} scored", _now_line(), ""]

    seen: set[str] = set()
    lines: list[str] = []
    for label, classes in _GROUPS:
        bucket = [r for r in ranked if (r.get("assetClass") or "") in classes]
        if not bucket:
            continue
        lines.append(f"<b>{label}</b>")
        for r in bucket:
            seen.add(r.get("id") or r.get("asset") or "")
            score = r.get("score") or 0
            d = r.get("dScore") or 0
            arrow = f" {'▲' if d > 0 else '▼'}{abs(d)}" if d else ""
            lines.append(
                f"  {score:>3} {_grade(score):<6} {_esc(r.get('asset')):<6} "
                f"{_esc(r.get('side') or ''):<5}{arrow}"
            )
        lines.append("")
    # Anything whose asset_class isn't in the three buckets still gets shown —
    # a silently-dropped ticker is worse than an untidy heading.
    rest = [r for r in ranked if (r.get("id") or r.get("asset") or "") not in seen]
    if rest:
        lines.append("<b>OTHER</b>")
        for r in rest:
            score = r.get("score") or 0
            lines.append(f"  {score:>3} {_grade(score):<6} {_esc(r.get('asset'))}")
    return _clip(lines, header)


def build_digest() -> list[tuple[str, str]]:
    """(name, html) for each drop, in send order."""
    from macro_positioning.dashboard import desk_data

    from macro_positioning.alerts import sentiment

    out = []
    for name, builder, formatter in (
        ("live", desk_data.build_live_signals_section, build_live_signals_message),
        ("hero", desk_data.build_hero_signals_section, build_hero_signals_message),
        ("watchlist", desk_data.build_watchlist_section, build_watchlist_message),
        # Which way names are turning — the earlier read than the score.
        ("sentiment", sentiment.load_shifts, sentiment.build_message),
    ):
        try:
            msg = formatter(builder())
        except Exception:  # noqa: BLE001
            # One failing section must not cost the other two.
            logger.exception("digest section %s failed", name)
            continue
        if msg:
            out.append((name, msg))
        else:
            logger.info("digest section %s is empty — skipped", name)
    return out


def send_digest() -> dict:
    from macro_positioning.alerts import notify

    results = {}
    for name, msg in build_digest():
        results[name] = notify.send_text(msg)
    return results
