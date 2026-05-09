"""Chart vision adapter — Piece 2 stub.

Piece 1 leaves this inert by design. Piece 2 will implement
`analyze_manual_chart()` by calling the existing
`macro_positioning.brain.vision.analyze_chart_file()` (Gemini 2.5 Pro)
with the prompt at `config/manual_chart_framework.md` and returning a
`TradeRecord`. Every call must satisfy `docs/logging_contract.md` —
write an `agent_call_log` row via the brain's `log_brain_call` helper.

The function exists now so the import surface and call site are stable;
flipping Piece 2 on is a body change, not a wiring change.
"""

from __future__ import annotations

from pathlib import Path

from macro_positioning.manual.models import TradeRecord


PROMPT_PATH = Path("config/manual_chart_framework.md")


def analyze_manual_chart(image_path: str | Path, asset_context: str = "") -> TradeRecord:
    """Run Gemini vision against a chart screenshot. Disabled in Piece 1.

    Raises:
        NotImplementedError: always, until Piece 2 lands.
    """
    raise NotImplementedError(
        "Manual chart vision is wired in Piece 2. See "
        "plans/manual-input-layer-also-hazy-island.md."
    )
