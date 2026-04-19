from __future__ import annotations

import hashlib
import re

from macro_positioning.core.models import NormalizedDocument, RawDocument


WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_text(raw_text: str) -> str:
    text = WHITESPACE_PATTERN.sub(" ", raw_text).strip()
    return text


def document_id_for(payload: RawDocument) -> str:
    base = f"{payload.source_id}|{payload.title}|{payload.published_at.isoformat()}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def normalize_document(payload: RawDocument) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=document_id_for(payload),
        source_id=payload.source_id,
        title=payload.title,
        url=payload.url,
        published_at=payload.published_at,
        author=payload.author,
        content_type=payload.content_type,
        raw_text=payload.raw_text,
        cleaned_text=clean_text(payload.raw_text),
        tags=payload.tags,
    )
