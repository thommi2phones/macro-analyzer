#!/usr/bin/env python3
"""Export integration contract schemas to JSON for the tactical-executor repo.

Run this whenever you change contracts.py. It writes a versioned schema file
that both repos can reference as the single source of truth.

Usage:
    python scripts/export_integration_schema.py

Output:
    integration_schema/macro_schema_v{VERSION}.json

Copy that file into the tactical-executor repo at /integration/ for the
other side to consume.
"""

from __future__ import annotations

import json
from pathlib import Path

from macro_positioning.integration.contracts import (
    CONTRACT_VERSION,
    MacroOutcomeAck,
    MacroOutcomeReport,
    MacroPositioningView,
)


def main() -> None:
    out_dir = Path("integration_schema")
    out_dir.mkdir(exist_ok=True)

    schema = {
        "contract_version": CONTRACT_VERSION,
        "schemas": {
            "MacroPositioningView": MacroPositioningView.model_json_schema(),
            "MacroOutcomeReport": MacroOutcomeReport.model_json_schema(),
            "MacroOutcomeAck": MacroOutcomeAck.model_json_schema(),
        },
        "endpoints": {
            "GET /positioning/view": {
                "description": "Per-asset macro directional view",
                "query_params": {
                    "asset": "Ticker symbol (required)",
                    "asset_class": "Optional override",
                },
                "response_model": "MacroPositioningView",
            },
            "GET /positioning/regime": {
                "description": "Overall macro regime summary",
                "response_type": "dict",
            },
            "POST /source-scoring/outcome": {
                "description": "Trade outcome feedback from tactical → macro",
                "request_model": "MacroOutcomeReport",
                "response_model": "MacroOutcomeAck",
            },
        },
    }

    out_path = out_dir / f"macro_schema_v{CONTRACT_VERSION}.json"
    out_path.write_text(json.dumps(schema, indent=2))
    print(f"✓ Wrote {out_path}")
    print(f"  Contract version: {CONTRACT_VERSION}")
    print(f"  Copy to tactical-executor repo at: /integration/macro_schema.json")


if __name__ == "__main__":
    main()
