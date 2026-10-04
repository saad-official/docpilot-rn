"""The persistence boundary: one `Store` protocol, two implementations.

    PostgresStore   production (Neon + pgvector), db/postgres.py
    MemoryStore     tests and local experiments without a database

Synchronous on purpose (same reasoning as Changelog Forge): llm-kit is synchronous, the
answer stream runs in a worker thread, and psycopg 3's sync API is callable from it
directly. At a few questions per minute driver throughput is irrelevant.
"""

from __future__ import annotations

import math
import re
import threading
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from ..models import Chunk, CorpusInfo, DocumentRecord, RetrievedChunk, utcnow

QuestionStatus = Literal["pending", "done", "failed"]


class QuestionRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utcnow)
    sdk: str
    version: str
    compare_version: str | None = None
    mode: Literal["answer", "diff"] = "answer"
    question: str
    rewritten: str | None = None
    retrieval: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None
    citations: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    status: QuestionStatus = "pending"
    error: str | None = None
    feedback: Literal["up", "down"] | None = None
    client_key: str | None = None


QUESTION_UPDATABLE = {
    "rewritten",
    "retrieval",
    "answer",
    "citations",
    "verification",
    "diff",
    "usage",
    "latency_ms",
    "status",
    "error",
}


class Store(Protocol):
    def ping(self) -> bool: ...
    def list_corpora(self) -> list[CorpusInfo]: ...
    def vector_search(
        self, sdk: str, versions: list[str], vector: list[float], limit: int
    ) -> list[RetrievedChunk]: ...
    def fulltext_search(
        self, sdk: str, versions: list[str], english: str, simple: str, limit: int
    ) -> list[RetrievedChunk]: ...

    def create_question(self, record: QuestionRecord) -> QuestionRecord: ...
    def update_question(self, question_id: str, **fields: Any) -> None: ...
    def get_question(self, question_id: str) -> QuestionRecord | None: ...
    def set_feedback(self, question_id: str, feedback: str) -> bool: ...
    def count_questions_since(self, client_key: str, since: datetime) -> int: ...
    def put_eval_run(
        self, golden_version: str, config: dict[str, Any], metrics: dict[str, Any]
    ) -> str: ...


class IngestStore(Protocol):
    """What ingestion needs on top of the embedding cache."""

    def get_embeddings(
        self, model: str, dimensions: int, hashes: list[str]
    ) -> dict[str, list[float]]: ...
    def put_embeddings(
        self, model: str, dimensions: int, items: list[tuple[str, list[float]]]
    ) -> None: ...
    def sync_corpus(
        self,
        *,
        sdk: str,
        repo: str,
        licence: str,
        attribution_url: str,
        version: str,
        commit_sha: str,
        embedding_model: str,
        dimensions: int,
        documents: list[DocumentRecord],
        chunks: list[Chunk],
        embeddings: dict[str, list[float]],
        stats: dict[str, Any],
    ) -> dict[str, int]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][\w.-]*", text.lower())


class MemoryStore:
    """A thread-safe in-process Store + IngestStore. Same contract, no durability; its
    full-text search is a crude term-overlap score, good enough for tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.corpora: dict[tuple[str, str], CorpusInfo] = {}
        self.chunks: dict[str, Chunk] = {}
        self.vectors: dict[str, list[float]] = {}
        self.embedding_cache: dict[tuple[str, str, int], list[float]] = {}
        self.questions: dict[str, QuestionRecord] = {}
        self.eval_runs: list[dict[str, Any]] = []

    # -- read side ---------------------------------------------------------------------
    def ping(self) -> bool:
        return True

    def list_corpora(self) -> list[CorpusInfo]:
        with self._lock:
            return list(self.corpora.values())

    @staticmethod
    def _retrieved(chunk: Chunk, score: float) -> RetrievedChunk:
        return RetrievedChunk(
            id=chunk.id,
            sdk=chunk.sdk,
            version=chunk.version,
            title=chunk.title,
            heading_path=chunk.heading_path,
            anchor=chunk.anchor,
            url=chunk.url,
            kind=chunk.kind,
            content=chunk.content,
            tokens=chunk.tokens,
            score=score,
        )

    def vector_search(
        self, sdk: str, versions: list[str], vector: list[float], limit: int
    ) -> list[RetrievedChunk]:
        with self._lock:
            scored = [
                (_cosine(vector, self.vectors[c.id]), c)
                for c in self.chunks.values()
                if c.sdk == sdk and c.version in versions and c.id in self.vectors
            ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [self._retrieved(c, s) for s, c in scored[:limit]]

    def fulltext_search(
        self, sdk: str, versions: list[str], english: str, simple: str, limit: int
    ) -> list[RetrievedChunk]:
        query_terms = {t.strip() for t in f"{english} or {simple}".lower().split(" or ")}
        query_terms.discard("")
        scored: list[tuple[float, Chunk]] = []
        with self._lock:
            for chunk in self.chunks.values():
                if chunk.sdk != sdk or chunk.version not in versions:
                    continue
                words = set(_words(f"{chunk.title} {chunk.heading_path} {chunk.content}"))
                hits = sum(
                    1 for t in query_terms if t in words or any(w.startswith(t) for w in words)
                )
                if hits:
                    scored.append((hits / (hits + 1), chunk))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [self._retrieved(c, s) for s, c in scored[:limit]]

    # -- questions -----------------------------------------------------------------------
    def create_question(self, record: QuestionRecord) -> QuestionRecord:
        with self._lock:
            self.questions[record.id] = record.model_copy(deep=True)
            return record

    def update_question(self, question_id: str, **fields: Any) -> None:
        unknown = set(fields) - QUESTION_UPDATABLE
        if unknown:
            raise ValueError(f"not updatable question fields: {sorted(unknown)}")
        with self._lock:
            current = self.questions[question_id]
            self.questions[question_id] = current.model_copy(update=fields)

    def get_question(self, question_id: str) -> QuestionRecord | None:
        with self._lock:
            record = self.questions.get(question_id)
            return record.model_copy(deep=True) if record else None

    def set_feedback(self, question_id: str, feedback: str) -> bool:
        with self._lock:
            if question_id not in self.questions:
                return False
            self.questions[question_id] = self.questions[question_id].model_copy(
                update={"feedback": feedback}
            )
            return True

    def count_questions_since(self, client_key: str, since: datetime) -> int:
        with self._lock:
            return sum(
                1
                for q in self.questions.values()
                if q.client_key == client_key and q.created_at >= since
            )

    def put_eval_run(
        self, golden_version: str, config: dict[str, Any], metrics: dict[str, Any]
    ) -> str:
        eval_id = str(uuid4())
        with self._lock:
            self.eval_runs.append(
                {"id": eval_id, "golden_version": golden_version, "config": config, **metrics}
            )
        return eval_id

    # -- ingestion -------------------------------------------------------------------------
    def get_embeddings(
        self, model: str, dimensions: int, hashes: list[str]
    ) -> dict[str, list[float]]:
        with self._lock:
            return {
                h: self.embedding_cache[(h, model, dimensions)]
                for h in hashes
                if (h, model, dimensions) in self.embedding_cache
            }

    def put_embeddings(
        self, model: str, dimensions: int, items: list[tuple[str, list[float]]]
    ) -> None:
        with self._lock:
            for content_hash, vector in items:
                self.embedding_cache[(content_hash, model, dimensions)] = vector

    def sync_corpus(
        self,
        *,
        sdk: str,
        repo: str,
        licence: str,
        attribution_url: str,
        version: str,
        commit_sha: str,
        embedding_model: str,
        dimensions: int,
        documents: list[DocumentRecord],
        chunks: list[Chunk],
        embeddings: dict[str, list[float]],
        stats: dict[str, Any],
    ) -> dict[str, int]:
        with self._lock:
            key = (sdk, version)
            existing = self.corpora.get(key)
            corpus_id = existing.id if existing else len(self.corpora) + 1
            old_ids = {cid for cid, c in self.chunks.items() if (c.sdk, c.version) == key}
            new_ids = {c.id for c in chunks}
            for cid in old_ids - new_ids:
                self.chunks.pop(cid, None)
                self.vectors.pop(cid, None)
            for chunk in chunks:
                self.chunks[chunk.id] = chunk
                vector = embeddings.get(chunk.content_hash) or self.embedding_cache.get(
                    (chunk.content_hash, embedding_model, dimensions)
                )
                if vector is not None:
                    self.vectors[chunk.id] = vector
            embedded = sum(1 for c in chunks if c.id in self.vectors)
            self.corpora[key] = CorpusInfo(
                id=corpus_id,
                sdk=sdk,  # type: ignore[arg-type]
                version=version,
                repo=repo,
                licence=licence,
                attribution_url=attribution_url,
                commit_sha=commit_sha,
                embedding_model=embedding_model,
                dimensions=dimensions,
                chunk_count=len(chunks),
                document_count=len(documents),
                embedded_count=embedded,
                ingested_at=utcnow(),
                stats=stats,
            )
            return {
                "upserted": len(new_ids),
                "removed": len(old_ids - new_ids),
                "new": len(new_ids - old_ids),
                "embedded": embedded,
            }
