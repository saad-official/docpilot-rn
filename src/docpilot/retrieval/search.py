"""Hybrid retrieval: vector top-40 + full-text top-40 -> RRF (+ API boost) -> optional rerank.

    question ──embed──> pgvector cosine top-40 ─┐
            └─terms──> Postgres FTS top-40  ────┴─> RRF k=60 + exact-API boost
                                                     └─> (Voyage rerank top-40 -> 8)
                                                         └─> context assembly [1]..[8]

Four configurations exist so the eval can compare them on the same golden set:
`vector`, `fulltext`, `hybrid`, `hybrid_rerank` (falls back to `hybrid` without a key).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..embeddings import EmbeddingError, EmbeddingProvider
from ..models import CorpusInfo, RetrievedChunk
from . import query as q
from .fusion import api_boost, order, rrf
from .rerank import VoyageReranker
from .sql import versions_for

Config = Literal["vector", "fulltext", "hybrid", "hybrid_rerank"]
CONFIGS: tuple[Config, ...] = ("vector", "fulltext", "hybrid", "hybrid_rerank")
CANDIDATES = 40


class RetrievalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class RetrievalResult(BaseModel):
    config: str
    effective_config: str
    query: str
    sdk: str
    versions: list[str]
    api_names: list[str] = Field(default_factory=list)
    chunks: list[RetrievedChunk]  # best first
    trace: dict[str, Any] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    rerank_tokens: int = 0
    rerank_usd: float = 0.0


class Retriever:
    def __init__(
        self,
        store: Any,
        embedder: EmbeddingProvider | None,
        *,
        reranker: VoyageReranker | None = None,
        candidates: int = CANDIDATES,
        rerank_top: int = 8,
        corpora_ttl_s: float = 60.0,
    ):
        self.store = store
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.rerank_top = rerank_top
        self.corpora_ttl_s = corpora_ttl_s
        self._corpora: tuple[float, list[CorpusInfo]] | None = None
        self._query_vectors: OrderedDict[str, list[float]] = OrderedDict()

    # ------------------------------------------------------------------ corpora

    def corpora(self) -> list[CorpusInfo]:
        now = time.monotonic()
        if self._corpora is None or now - self._corpora[0] > self.corpora_ttl_s:
            self._corpora = (now, self.store.list_corpora())
        return self._corpora[1]

    def check(self, sdk: str, version: str, *, include_shared: bool = True) -> list[str]:
        """Versions to search; raises when the version is unknown or embedded differently."""
        corpora = [c for c in self.corpora() if c.sdk == sdk]
        known = {c.version for c in corpora}
        if version not in known:
            raise RetrievalError(
                "unknown_version",
                f"no {sdk} corpus for version {version!r}; available: {sorted(known)}",
            )
        wanted = versions_for(sdk, version, include_shared=include_shared)
        versions = [v for v in wanted if v in known]
        if self.embedder is not None:
            for corpus in corpora:
                if corpus.version in versions and corpus.embedding_model != self.embedder.model:
                    raise RetrievalError(
                        "embedding_model_mismatch",
                        f"{sdk}@{corpus.version} was embedded with {corpus.embedding_model}; "
                        f"the query side uses {self.embedder.model}. Re-ingest or switch "
                        "EMBEDDING_PROVIDER back (one embedding model per corpus).",
                    )
        return versions

    # ------------------------------------------------------------------ steps

    def embed_query(self, text: str) -> list[float]:
        if self.embedder is None:
            raise RetrievalError("embeddings_unavailable", "no embedding provider configured")
        if text in self._query_vectors:
            self._query_vectors.move_to_end(text)
            return self._query_vectors[text]
        vector = self.embedder.embed([text], "query")[0]
        self._query_vectors[text] = vector
        if len(self._query_vectors) > 256:
            self._query_vectors.popitem(last=False)
        return vector

    def retrieve(
        self,
        query: str,
        *,
        sdk: str,
        version: str,
        config: Config = "hybrid",
        include_shared: bool = True,
    ) -> RetrievalResult:
        versions = self.check(sdk, version, include_shared=include_shared)
        names = q.api_names(query)
        timings: dict[str, float] = {}
        trace: dict[str, Any] = {}
        by_id: dict[str, RetrievedChunk] = {}
        rankings: dict[str, list[str]] = {}

        vector: list[float] | None = None
        if config != "fulltext":
            started = time.monotonic()
            try:
                vector = self.embed_query(query)
            except EmbeddingError as exc:
                # The query side shares the embedding provider's quota with ingestion. When
                # it is exhausted, hybrid degrades to full-text instead of failing.
                if config == "vector":
                    raise RetrievalError("embeddings_unavailable", str(exc)) from exc
                trace["vector"] = f"unavailable: {str(exc)[:200]}"
            timings["embed"] = (time.monotonic() - started) * 1000
        if vector is not None:
            started = time.monotonic()
            hits = self.store.vector_search(sdk, versions, vector, self.candidates)
            timings["vector"] = (time.monotonic() - started) * 1000
            rankings["vector"] = [h.id for h in hits]
            trace["vector"] = [[h.id, round(h.score, 5)] for h in hits]
            for rank, hit in enumerate(hits, start=1):
                hit.scores.update(vector=round(hit.score, 6), vector_rank=rank)
                by_id[hit.id] = hit

        if config != "vector":
            started = time.monotonic()
            hits = self.store.fulltext_search(
                sdk, versions, q.english_query(query), q.simple_query(query), self.candidates
            )
            timings["fulltext"] = (time.monotonic() - started) * 1000
            rankings["fulltext"] = [h.id for h in hits]
            trace["fulltext"] = [[h.id, round(h.score, 5)] for h in hits]
            for rank, hit in enumerate(hits, start=1):
                existing = by_id.setdefault(hit.id, hit)
                existing.scores.update(fulltext=round(hit.score, 6), fulltext_rank=rank)

        if config in ("vector", "fulltext") or "vector" not in rankings:
            mode = config if config in ("vector", "fulltext") else "fulltext"
            ids = rankings[mode]
            for chunk_id in ids:
                by_id[chunk_id].score = by_id[chunk_id].scores[mode]
            result_ids = ids
        else:
            fused = rrf(rankings)
            for chunk_id, score in fused.items():
                chunk = by_id[chunk_id]
                boost = api_boost(names, f"{chunk.title} {chunk.heading_path}", chunk.content)
                chunk.scores.update(rrf=round(score, 6), boost=round(boost, 6))
                fused[chunk_id] = score + boost
                chunk.score = round(fused[chunk_id], 6)
            result_ids = order(fused)[: self.candidates]
            trace["fused"] = [[i, round(fused[i], 6)] for i in result_ids]

        effective: str = config
        if "vector" not in rankings and config != "fulltext":
            effective = "fulltext"
        rerank_tokens, rerank_usd = 0, 0.0
        if config == "hybrid_rerank" and "vector" in rankings:
            if self.reranker is None:
                effective = "hybrid"
                trace["rerank"] = "unavailable (no VOYAGE_API_KEY); RRF order used"
            else:
                started = time.monotonic()
                candidates = [by_id[i] for i in result_ids]
                result = self.reranker.rerank(
                    query,
                    [f"{c.title} › {c.heading_path}\n{c.content}" for c in candidates],
                    top_k=self.rerank_top,
                )
                timings["rerank"] = (time.monotonic() - started) * 1000
                reranked = []
                for index, score in zip(result.order, result.scores, strict=True):
                    chunk = candidates[index]
                    chunk.scores["rerank"] = round(score, 6)
                    chunk.score = round(score, 6)
                    reranked.append(chunk.id)
                rest = [i for i in result_ids if i not in set(reranked)]
                result_ids = reranked + rest
                trace["reranked"] = [[i, by_id[i].scores["rerank"]] for i in reranked]
                rerank_tokens, rerank_usd = result.tokens, result.cost_usd

        return RetrievalResult(
            config=config,
            effective_config=effective,
            query=query,
            sdk=sdk,
            versions=versions,
            api_names=names,
            chunks=[by_id[i] for i in result_ids],
            trace=trace,
            timings_ms={k: round(v, 1) for k, v in timings.items()},
            rerank_tokens=rerank_tokens,
            rerank_usd=rerank_usd,
        )
