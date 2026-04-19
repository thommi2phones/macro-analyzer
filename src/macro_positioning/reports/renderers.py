from __future__ import annotations

from pathlib import Path

from macro_positioning.core.models import (
    PositioningMemo,
    PositioningRecommendation,
    ValidatedThesis,
)


def render_memo_markdown(
    memo: PositioningMemo,
    validated_theses: list[ValidatedThesis],
    recommendations: list[PositioningRecommendation],
) -> str:
    lines = [
        f"# {memo.title}",
        "",
        f"*Generated: {memo.generated_at.isoformat()}*",
        "",
        "## TL;DR",
        memo.summary,
        "",
        "## Consensus Views",
    ]
    lines.extend(f"- {item}" for item in memo.consensus_views or ["No consensus views yet."])

    lines.extend(["", "## Divergent Views"])
    lines.extend(f"- {item}" for item in memo.divergent_views or ["No meaningful divergence detected."])

    lines.extend(["", "## Suggested Positioning"])
    if recommendations:
        for item in recommendations:
            expr = "; ".join(item.expression) or "n/a"
            risks = "; ".join(item.risks) if item.risks else "none captured"
            lines.append(
                f"- **{item.title}** (horizon {item.horizon}, conf {item.confidence:.2f})\n"
                f"  - Rationale: {item.rationale}\n"
                f"  - Expressions: {expr}\n"
                f"  - Risks: {risks}"
            )
    else:
        lines.append("- No supported recommendations passed the support threshold.")

    lines.extend(["", "## Expert vs Market"])
    lines.extend(f"- {item}" for item in memo.expert_vs_market or ["No validated theses yet."])

    lines.extend(["", "## Risks to Watch"])
    lines.extend(f"- {item}" for item in memo.risks_to_watch or ["No explicit risks captured yet."])

    lines.extend(["", "## Thesis Tracker"])
    if validated_theses:
        ranked = sorted(
            validated_theses,
            key=lambda v: v.validation.support_score,
            reverse=True,
        )
        for item in ranked:
            thesis = item.thesis
            v = item.validation
            sources = ", ".join(thesis.source_ids) or "unknown"
            lines.append(
                f"- [{thesis.theme}] *{thesis.direction.value}* — {thesis.thesis}\n"
                f"  - horizon: {thesis.horizon} | support: {v.support_score:.2f} | "
                f"alignment: {v.sentiment_alignment} | sources: {sources}"
            )
    else:
        lines.append("- No theses available.")

    lines.extend(["", "## Inputs Still Needed"])
    lines.extend(f"- {item}" for item in memo.required_inputs or ["No outstanding inputs listed."])
    return "\n".join(lines) + "\n"


def write_memo_markdown(output_path: Path, content: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    return output_path
