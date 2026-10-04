"""Shared domain types. Pydantic at every boundary: ingestion output, retrieval results,
verification reports and the API all speak these."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Sdk = Literal["expo", "react-native"]
ChunkKind = Literal["prose", "code", "table"]
Mode = Literal["answer", "diff"]

HEADING_SEP = " › "


def utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentRecord(BaseModel):
    id: str
    sdk: Sdk
    version: str
    path: str
    url: str
    title: str
    description: str | None = None
    platforms: list[str] = Field(default_factory=list)
    content_hash: str


class Chunk(BaseModel):
    id: str
    document_id: str
    sdk: Sdk
    version: str
    ordinal: int
    title: str
    heading_path: str
    anchor: str | None
    url: str
    kind: ChunkKind
    content: str
    tokens: int
    content_hash: str  # sha256 of embed_text: the embedding cache key

    @property
    def embed_text(self) -> str:
        """What is embedded: the page title and heading path give a short chunk the context
        it lost when it was cut out of its page ("Setup" alone means nothing)."""
        return f"{self.title}\n{self.heading_path}\n\n{self.content}"


class RetrievedChunk(BaseModel):
    """A chunk as retrieval returns it, with the score from every stage that saw it."""

    id: str
    sdk: str
    version: str
    title: str
    heading_path: str
    anchor: str | None = None
    url: str
    kind: str = "prose"
    content: str
    tokens: int = 0
    scores: dict[str, float] = Field(default_factory=dict)
    score: float = 0.0


class CorpusInfo(BaseModel):
    id: int
    sdk: Sdk
    version: str
    repo: str
    licence: str
    attribution_url: str
    commit_sha: str
    embedding_model: str
    dimensions: int
    chunk_count: int
    document_count: int = 0
    embedded_count: int | None = None  # chunks with a vector (< chunk_count while partial)
    ingested_at: datetime
    stats: dict[str, Any] = Field(default_factory=dict)
