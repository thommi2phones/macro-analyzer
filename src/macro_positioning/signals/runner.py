"""Batch signal extraction.

Pulls pending documents, routes each through the appropriate extractor,
persists Signal rows + attempt log. One run_id per `extract_pending()`
call so we can audit / roll back a bad extraction batch.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from macro_positioning.signals import repository
from macro_positioning.signals.base import ExtractionResult
from macro_positioning.signals.router import build_registry, choose_extractors

log = logging.getLogger(__name__)


@dataclass
class ExtractionRunSummary:
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    docs_seen: int = 0
    docs_with_signals: int = 0
    docs_no_signal: int = 0
    docs_error: int = 0
    signals_written: int = 0
    by_extractor: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "docs_seen": self.docs_seen,
            "docs_with_signals": self.docs_with_signals,
            "docs_no_signal": self.docs_no_signal,
            "docs_error": self.docs_error,
            "signals_written": self.signals_written,
            "by_extractor": self.by_extractor,
            "errors": self.errors[:20],   # cap for printability
        }


def extract_pending(
    *,
    limit: int = 100,
    since_days: int = 30,
    extractor_filter: Optional[str] = None,
    db_path: Optional[Path] = None,
    dry_run: bool = False,
) -> ExtractionRunSummary:
    """Extract signals from every document not yet successfully extracted.

    Args:
      limit: cap number of docs processed per run.
      since_days: only consider docs ingested within this window.
      extractor_filter: if set, only run that named extractor (skip others).
      dry_run: when True, do not persist signals or attempts — useful for
        development sanity checks.
    """
    from datetime import UTC, datetime as _dt

    run_id = uuid.uuid4().hex
    started = _dt.now(UTC).isoformat()
    summary = ExtractionRunSummary(run_id=run_id, started_at=started)

    registry = build_registry()
    current_versions = {name: ex.version for name, ex in registry.items()}
    pending = repository.pending_documents(
        limit=limit, since_days=since_days,
        extractor_name=extractor_filter,
        current_extractor_versions=current_versions,
        db_path=db_path,
    )
    summary.docs_seen = len(pending)
    log.info("signals.extract_pending: %d docs to process (run=%s)", len(pending), run_id)

    for doc in pending:
        extractor_names = choose_extractors(doc)
        if extractor_filter:
            extractor_names = [n for n in extractor_names if n == extractor_filter]
        if not extractor_names:
            continue

        any_success = False
        any_signals = False
        for name in extractor_names:
            extractor = registry.get(name)
            if extractor is None:
                log.warning("Unknown extractor %s — skipping", name)
                continue

            try:
                result: ExtractionResult = extractor.extract(doc, run_id=run_id)
            except Exception as exc:
                log.exception("Extractor %s crashed on doc %s", name, doc.get("document_id"))
                result = ExtractionResult(
                    document_id=doc["document_id"],
                    extractor_name=name,
                    extractor_version=extractor.version,
                    status="error",
                    error_message=f"{type(exc).__name__}: {exc}",
                )

            if not dry_run:
                repository.record_attempt(result, db_path=db_path)
                if result.signals:
                    repository.insert_signals(result.signals, db_path=db_path)

            if result.status == "success":
                any_success = True
            if result.signals:
                any_signals = True
                summary.signals_written += len(result.signals)
                summary.by_extractor[name] = (
                    summary.by_extractor.get(name, 0) + len(result.signals)
                )
            if result.status == "error":
                summary.errors.append({
                    "document_id": doc.get("document_id"),
                    "extractor": name,
                    "error": result.error_message,
                })

        if any_signals:
            summary.docs_with_signals += 1
        elif any_success:
            summary.docs_no_signal += 1
        else:
            summary.docs_error += 1

    summary.finished_at = _dt.now(UTC).isoformat()
    log.info(
        "signals.extract_pending complete: %s",
        summary.to_dict(),
    )
    return summary


def extract_for_document(
    document: dict,
    *,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
    persist: bool = True,
) -> dict:
    """Synchronous extraction for ONE document.

    Used by the manual ingest path for self-authored drops so the SPA's
    confirmation panel can render the extracted signals immediately.

    Defensive by design: any extractor crash is caught and surfaced as
    `error_message`. The document itself is never lost — even if every
    extractor fails, the doc remains in `pending_documents` for the
    next batch run.

    Args:
      document: dict shaped like a row from the `documents` table.
        Must include document_id; everything else is optional and routed
        through the same code paths as batch extraction.
      run_id: optional batch identifier — defaults to a new uuid.
      persist: when False, skip writes (useful for tests / dry runs).

    Returns:
      {
        run_id: str,
        signals: list[Signal-as-dict],     # for SPA rendering
        by_extractor: {name: count},
        error_message: str | None,
      }
    """
    import uuid as _uuid

    run_id = run_id or _uuid.uuid4().hex
    registry = build_registry()
    extractor_names = choose_extractors(document)

    out_signals: list[dict] = []
    by_extractor: dict[str, int] = {}
    errors: list[str] = []

    for name in extractor_names:
        extractor = registry.get(name)
        if extractor is None:
            continue
        try:
            result: ExtractionResult = extractor.extract(document, run_id=run_id)
        except Exception as exc:
            log.exception("Inline extractor %s crashed", name)
            result = ExtractionResult(
                document_id=document["document_id"],
                extractor_name=name,
                extractor_version=extractor.version,
                status="error",
                error_message=f"{type(exc).__name__}: {exc}",
            )

        if persist:
            repository.record_attempt(result, db_path=db_path)
            if result.signals:
                repository.insert_signals(result.signals, db_path=db_path)

        if result.signals:
            by_extractor[name] = by_extractor.get(name, 0) + len(result.signals)
            for s in result.signals:
                out_signals.append(_signal_preview(s))
        if result.status == "error" and result.error_message:
            errors.append(f"{name}: {result.error_message}")

    return {
        "run_id": run_id,
        "signals": out_signals,
        "by_extractor": by_extractor,
        "error_message": "; ".join(errors) if errors else None,
    }


def _signal_preview(signal) -> dict:
    """Compact dict the SPA can render without hydrating the full row."""
    return {
        "signal_id": signal.signal_id,
        "asset_ticker": signal.asset_ticker,
        "side": signal.side.value if hasattr(signal.side, "value") else str(signal.side),
        "conviction": signal.conviction,
        "horizon": signal.horizon.value if signal.horizon else None,
        "thesis_summary": signal.thesis_summary,
        "thesis_tags": signal.thesis_tags,
        "catalyst_type": (
            signal.catalyst_type.value if signal.catalyst_type else None
        ),
        "stop_loss": signal.stop_loss,
        "target_1": signal.target_1,
        "target_2": signal.target_2,
        "extractor_name": signal.extractor_name,
        "extractor_confidence": signal.extractor_confidence,
        "model_name": signal.model_name,
        "cost_usd": signal.cost_usd,
    }
