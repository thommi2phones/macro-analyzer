"""Narrative Synthesizer — LLM-backed thesis extraction.

Phase 4 ships an interface + heuristic stub. Real LLM call lands in
Phase 6, going through `logging_wrapper.log_agent_call` to satisfy
the logging contract.

The interface is what the orchestrator depends on. The implementation
behind it can swap from stub → Gemini-via-N8N → fine-tuned LLM without
the orchestrator caring.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SynthesisInput(BaseModel):
    """Documents + light context the synthesizer reads."""

    documents: list[dict] = Field(default_factory=list, description="RawDocument-like dicts")
    active_regime: str | None = None
    recent_theses: list[dict] = Field(default_factory=list)


class SynthesisOutput(BaseModel):
    """Structured theses + supporting evidence."""

    theses: list[dict] = Field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""


def synthesize_stub(payload: SynthesisInput) -> SynthesisOutput:
    """Heuristic stub. Returns one passthrough thesis per document so
    the orchestrator's wiring can be tested end-to-end without burning
    LLM tokens.

    Phase 6 will replace this with:
        log_agent_call(
            agent_name="narrative_synthesizer",
            model_provider="gemini",
            model_name="gemini-2.5-pro",
            prompt_version="narrative_synthesizer@v1",
            input_payload=payload.model_dump(),
            call_fn=lambda: gemini_via_n8n.synthesize(...),
            context={"active_regime": payload.active_regime},
        )
    """
    theses = []
    for doc in payload.documents[:5]:
        theses.append(
            {
                "thesis": f"[stub] passthrough of {doc.get('title', 'untitled')}",
                "source_id": doc.get("source_id"),
                "horizon": "unknown",
                "direction": "unknown",
                "confidence": 0.3,
            }
        )
    return SynthesisOutput(
        theses=theses,
        confidence=0.3,
        notes="STUB synthesizer — real LLM implementation pending Phase 6.",
    )
