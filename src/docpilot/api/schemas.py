"""Request and response models for the HTTP API (spec section 6). The web app codes against
these; OpenAPI at /api/docs is generated from them. Event payloads are documented in
docs/api.md."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_QUESTION_CHARS = 1000
MAX_THREAD_MESSAGES = 8


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    sdk: Literal["expo", "react-native"] = "expo"
    version: str = Field(min_length=1, max_length=32)
    mode: Literal["answer", "diff"] = "answer"
    compare_version: str | None = Field(default=None, max_length=32)
    thread: list[ThreadMessage] | None = Field(
        default=None,
        description="Up to 8 earlier messages (4 turns), oldest first; used only to rewrite "
        "a follow-up into a standalone search query.",
    )

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question is empty")
        return value

    @field_validator("thread")
    @classmethod
    def _last_turns(cls, value: list[ThreadMessage] | None) -> list[ThreadMessage] | None:
        # Older messages are ignored rather than rejected: the browser owns the thread.
        return value[-MAX_THREAD_MESSAGES:] if value else None

    @model_validator(mode="after")
    def _diff_needs_two(self) -> AskRequest:
        if self.mode == "diff":
            if not self.compare_version:
                raise ValueError("diff mode needs compare_version")
            if self.compare_version == self.version:
                raise ValueError("compare_version must differ from version")
            if self.sdk != "expo":
                raise ValueError("diff mode is available for Expo only (one React Native version)")
        return self


class FeedbackRequest(BaseModel):
    feedback: Literal["up", "down"]


class VersionView(BaseModel):
    version: str
    label: str
    chunk_count: int
    document_count: int
    embedded_count: int | None = Field(description="Chunks with a vector (coverage)")
    commit_sha: str
    ingested_at: datetime
    embedding_model: str
    dimensions: int
    shared: bool = Field(description="True for 'unversioned': searched with every version")


class SourceView(BaseModel):
    name: Literal["expo", "react-native"]
    label: str
    repo: str
    licence: str
    attribution_url: str
    embedding_model: str | None
    default_version: str | None
    versions: list[VersionView] = Field(description="Newest first; 'unversioned' last")


class VersionsResponse(BaseModel):
    sources: list[SourceView]


class QuestionView(BaseModel):
    id: str
    created_at: datetime
    question: str
    sdk: str
    version: str
    compare_version: str | None
    mode: Literal["answer", "diff"]
    status: str
    rewritten: str | None
    answer: str | None
    chunks: list[dict[str, Any]] = Field(description="Same shape as the retrieval event")
    citations: dict[str, Any] = Field(description="{verified, removed, unsupported}")
    verification: dict[str, Any]
    diff: dict[str, Any] | None
    usage: dict[str, Any]
    latency_ms: int | None
    feedback: Literal["up", "down"] | None
    error: str | None


class CorpusHealth(BaseModel):
    sdk: str
    version: str
    chunk_count: int
    embedded_count: int | None
    commit_sha: str
    ingested_at: datetime
    age_days: float
    stale: bool


class Health(BaseModel):
    ok: bool
    version: str
    db: bool
    store: Literal["postgres", "memory"]
    providers: dict[str, bool]
    embedding: dict[str, Any]
    rerank: bool
    corpora: list[CorpusHealth]


class ErrorBody(BaseModel):
    code: str
    message: str
    retry_after: int | None = Field(default=None, description="Seconds; also a header.")
    field: str | None = Field(default=None, description="The request field at fault.")
