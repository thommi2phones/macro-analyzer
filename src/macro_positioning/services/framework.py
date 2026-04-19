from __future__ import annotations

from macro_positioning.core.models import CredentialRequirement, SourceOnboardingRequest, SourcePriority, SourceType


def default_credential_requirements() -> list[CredentialRequirement]:
    return [
        CredentialRequirement(
            key="OPENAI_API_KEY",
            label="OpenAI API Key",
            required_for=["structured thesis extraction", "memo synthesis"],
            description="Used to upgrade extraction and synthesis from heuristic rules to model-backed outputs.",
        ),
        CredentialRequirement(
            key="TWITTER_API_KEY",
            label="X/Twitter API",
            required_for=["social ingestion"],
            description="Needed only if you want direct X ingestion from supported providers.",
            optional=True,
        ),
        CredentialRequirement(
            key="YOUTUBE_API_KEY",
            label="YouTube API",
            required_for=["video metadata and transcript discovery"],
            description="Useful for channels and interviews that carry macro views.",
            optional=True,
        ),
        CredentialRequirement(
            key="MARKET_DATA_API_KEY",
            label="Market Data API",
            required_for=["market validation"],
            description="Needed for price, curve, macro calendar, and related validation feeds.",
            optional=True,
        ),
    ]


def onboarding_template() -> list[SourceOnboardingRequest]:
    return [
        SourceOnboardingRequest(
            source={
                "source_id": "replace_me_source",
                "name": "Replace Me",
                "source_type": SourceType.newsletter,
                "priority": SourcePriority.core,
                "market_focus": ["macro"],
            },
            rationale="Why this source matters to your process.",
            required_credentials=[],
            implementation_notes=[
                "List every channel this source publishes on.",
                "Note whether the content is public, subscription, or private.",
                "State whether transcript access is available.",
            ],
        )
    ]
