"""Embedding providers behind one protocol, plus the content-hash cache and batching.

    EmbeddingProvider            what ingestion and the query path need
      GeminiEmbeddings           gemini-embedding-001, outputDimensionality=768
      VoyageEmbeddings           voyage-4-lite, 1024-d (used when VOYAGE_API_KEY is set)

One model per corpus: vectors from two models live in unrelated spaces, so a query
embedded with model A compared against documents embedded with model B returns confident
nonsense rather than an error. The corpus row records `embedding_model` and `dimensions`;
the retriever refuses to search a corpus with a different model (see retrieval/search.py).

Every call is recorded in an `EmbeddingLedger` (calls, texts, tokens, cost at paid rates),
the embeddings counterpart of llm-kit's Ledger. Neither provider's batch endpoint reports
token usage for Gemini, so Gemini tokens are counted locally with o200k_base and labelled
as an estimate.

Why not llm-kit: llm-kit speaks the OpenAI chat wire format. Gemini's OpenAI-compatible
endpoint does expose `/embeddings`, but not `taskType` (query vs document embeddings, which
measurably helps retrieval) and with a smaller batch; Voyage has no OpenAI-compatible
endpoint at all. Two small HTTP clients are less code than bending the chat client.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

from .tokens import TokenCounter, default_counter

log = logging.getLogger(__name__)

InputType = Literal["document", "query"]

# USD per 1M input tokens at paid rates (checked 2026-10-04 on the vendors' pricing pages;
# both have free allowances: Gemini's free tier, Voyage's 200M free tokens per account).
EMBEDDING_PRICES: dict[str, float] = {
    "gemini-embedding-001": 0.15,
    "voyage-4-lite": 0.02,
    "rerank-2.5-lite": 0.02,
}
EMBEDDING_PRICES_VERIFIED_ON = "2026-10-04"


class EmbeddingError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        transient: bool = False,
        daily: bool = False,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.transient = transient
        # A daily quota wall (Gemini free tier: 1,000 embedded texts per day per model,
        # each text in a batch counting as one request). Waiting will not help today.
        self.daily = daily


@dataclass
class EmbeddingRecord:
    provider: str
    model: str
    texts: int
    tokens: int
    tokens_estimated: bool
    latency_s: float
    attempts: int = 1
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        return self.tokens * EMBEDDING_PRICES.get(self.model, 0.0) / 1_000_000


@dataclass
class EmbeddingLedger:
    records: list[EmbeddingRecord] = field(default_factory=list)

    def add(self, record: EmbeddingRecord) -> None:
        self.records.append(record)

    @property
    def tokens(self) -> int:
        return sum(r.tokens for r in self.records)

    @property
    def total_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def summary(self) -> str:
        texts = sum(r.texts for r in self.records)
        estimated = any(r.tokens_estimated for r in self.records)
        return (
            f"{len(self.records)} embedding calls  {texts} texts  "
            f"{self.tokens} tokens{' (estimated, o200k_base)' if estimated else ''}  "
            f"${self.total_usd:.6f} at paid rates"
        )


class EmbeddingProvider(Protocol):
    provider: str
    model: str
    dimensions: int
    max_batch: int
    ledger: EmbeddingLedger

    def embed(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]: ...


def l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


_QUOTA_RE = re.compile(r"Quota exceeded for metric: [^\n\"\\]*")
_RETRY_DELAY_RE = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


def _retry_after(response: httpx.Response) -> float | None:
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _RETRY_DELAY_RE.search(response.text)
    return float(match.group(1)) if match else None


class _HttpEmbedder:
    """Shared retry loop: 429/5xx/transport errors back off (honouring the provider's
    retry hint) until `deadline_s`; anything else fails fast."""

    provider = ""
    model = ""
    dimensions = 0
    max_batch = 100

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        deadline_s: float = 300.0,
        counter: TokenCounter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))
        self.deadline_s = deadline_s
        self.counter = counter
        self.sleep = sleep
        self.ledger = EmbeddingLedger()

    def _request(self, texts: Sequence[str], input_type: InputType) -> httpx.Response:
        raise NotImplementedError

    def _parse(self, response: httpx.Response) -> tuple[list[list[float]], int | None]:
        raise NotImplementedError

    def embed(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > self.max_batch:
            raise ValueError(f"batch of {len(texts)} exceeds {self.max_batch}")
        started = time.monotonic()
        attempt = 0
        while True:
            attempt += 1
            error: EmbeddingError
            try:
                response = self._request(texts, input_type)
            except httpx.TransportError as exc:
                error = EmbeddingError(f"transport failure: {exc}", transient=True)
            else:
                if response.status_code < 300:
                    vectors, tokens = self._parse(response)
                    if len(vectors) != len(texts):
                        raise EmbeddingError(f"{len(texts)} texts in, {len(vectors)} vectors out")
                    estimated = tokens is None
                    if tokens is None:
                        counter = self.counter or default_counter()
                        tokens = sum(counter.count(t) for t in texts)
                    self.ledger.add(
                        EmbeddingRecord(
                            self.provider,
                            self.model,
                            len(texts),
                            tokens,
                            estimated,
                            time.monotonic() - started,
                            attempt,
                        )
                    )
                    return [l2_normalise(v) for v in vectors]
                transient = response.status_code in (408, 429) or response.status_code >= 500
                retry_after = _retry_after(response)
                quota = _QUOTA_RE.search(response.text)
                error = EmbeddingError(
                    f"{self.provider} embeddings returned {response.status_code}: "
                    + (quota.group(0) if quota else response.text[:300]),
                    retry_after=retry_after,
                    transient=transient,
                    daily="PerDay" in response.text
                    or (retry_after is not None and retry_after > 3600),
                )
            elapsed = time.monotonic() - started
            if error.retry_after is not None:
                delay = error.retry_after
            elif "returned 429" in str(error):
                delay = min(65.0, 20.0 * attempt)  # a per-minute quota: wait for the window
            else:
                delay = min(60.0, 2.0**attempt)
            if not error.transient or elapsed + delay > self.deadline_s:
                self.ledger.add(
                    EmbeddingRecord(
                        self.provider,
                        self.model,
                        len(texts),
                        0,
                        True,
                        elapsed,
                        attempt,
                        error=str(error)[:300],
                    )
                )
                raise error
            log.warning("embedding call failed (%s); retrying in %.1fs", str(error)[:120], delay)
            self.sleep(delay + 0.5)


class GeminiEmbeddings(_HttpEmbedder):
    provider = "gemini"
    model = "gemini-embedding-001"
    max_batch = 100
    url = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"

    def __init__(self, api_key: str, *, dimensions: int = 768, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(api_key, **kwargs)
        self.dimensions = dimensions

    def _request(self, texts: Sequence[str], input_type: InputType) -> httpx.Response:
        task = "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task,
                    "outputDimensionality": self.dimensions,
                }
                for text in texts
            ]
        }
        return self.client.post(
            self.url.format(model=self.model),
            json=body,
            headers={"x-goog-api-key": self.api_key},
        )

    def _parse(self, response: httpx.Response) -> tuple[list[list[float]], int | None]:
        return [item["values"] for item in response.json()["embeddings"]], None


class VoyageEmbeddings(_HttpEmbedder):
    provider = "voyage"
    model = "voyage-4-lite"
    max_batch = 100  # Voyage allows 1,000 texts / 1M tokens per call; 100 keeps calls small
    url = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, api_key: str, *, dimensions: int = 1024, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(api_key, **kwargs)
        self.dimensions = dimensions

    def _request(self, texts: Sequence[str], input_type: InputType) -> httpx.Response:
        return self.client.post(
            self.url,
            json={
                "input": list(texts),
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dimensions,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    def _parse(self, response: httpx.Response) -> tuple[list[list[float]], int | None]:
        body = response.json()
        data = sorted(body["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data], body.get("usage", {}).get("total_tokens")


def make_embedder(settings, **kwargs) -> EmbeddingProvider:  # type: ignore[no-untyped-def]
    """The configured provider. Raises ValueError when its key is missing."""
    name = settings.resolved_embedding_provider
    if name == "voyage":
        if not settings.has_key("voyage"):
            raise ValueError("EMBEDDING_PROVIDER=voyage but VOYAGE_API_KEY is not set")
        return VoyageEmbeddings(
            settings.voyage_api_key.get_secret_value(),
            dimensions=settings.embedding_dimensions,
            **kwargs,
        )
    if not settings.has_key("gemini"):
        raise ValueError("GEMINI_API_KEY is not set (needed for gemini-embedding-001)")
    return GeminiEmbeddings(
        settings.gemini_api_key.get_secret_value(),
        dimensions=settings.embedding_dimensions,
        **kwargs,
    )


# ----------------------------------------------------------------------------- cache


class EmbeddingCache(Protocol):
    """Vectors keyed by (content hash, model, dimensions). Unchanged text is never
    re-embedded, so re-ingesting after an upstream docs change only pays for what changed,
    and an ingestion that died half-way resumes where it stopped."""

    def get_embeddings(
        self, model: str, dimensions: int, hashes: list[str]
    ) -> dict[str, list[float]]: ...

    def put_embeddings(
        self, model: str, dimensions: int, items: list[tuple[str, list[float]]]
    ) -> None: ...


class MemoryEmbeddingCache:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str, int], list[float]] = {}

    def get_embeddings(
        self, model: str, dimensions: int, hashes: list[str]
    ) -> dict[str, list[float]]:
        return {
            h: self.data[(h, model, dimensions)]
            for h in hashes
            if (h, model, dimensions) in self.data
        }

    def put_embeddings(
        self, model: str, dimensions: int, items: list[tuple[str, list[float]]]
    ) -> None:
        for content_hash, vector in items:
            self.data[(content_hash, model, dimensions)] = vector


@dataclass
class EmbedReport:
    total: int = 0
    cached: int = 0
    embedded: int = 0
    batches: int = 0
    missing: int = 0  # texts left without a vector (quota wall or --max-embed)
    stopped: str | None = None


def plan_batches(
    items: list[tuple[str, str]],
    *,
    max_items: int,
    max_tokens: int | None,
    counter: TokenCounter,
) -> list[list[tuple[str, str, int]]]:
    """Split (hash, text) pairs into batches bounded by item count *and* token count.

    Count alone is not enough: Gemini's free tier also limits tokens per minute, and 100
    chunks of ~400 tokens is one request over that limit - rejected on every retry (found
    on the first live run: the first React Native batch, ~36k tokens, never succeeded).
    """
    batches: list[list[tuple[str, str, int]]] = []
    current: list[tuple[str, str, int]] = []
    used = 0
    for content_hash, text in items:
        size = counter.count(text)
        if current and (len(current) >= max_items or (max_tokens and used + size > max_tokens)):
            batches.append(current)
            current, used = [], 0
        current.append((content_hash, text, size))
        used += size
    if current:
        batches.append(current)
    return batches


def embed_with_cache(
    provider: EmbeddingProvider,
    cache: EmbeddingCache,
    items: list[tuple[str, str]],
    *,
    batch_size: int = 100,
    batch_tokens: int | None = 20_000,
    tpm_limit: int | None = 25_000,
    pause_s: float = 0.0,
    counter: TokenCounter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_batch: Callable[[int, int], None] | None = None,
    max_new: int | None = None,
) -> tuple[dict[str, list[float]], EmbedReport]:
    """Embed `(content_hash, text)` pairs, consulting and filling the cache.

    Each batch is written to the cache as soon as it returns, so a crash (or a quota wall)
    loses at most one batch of work. Duplicate hashes are embedded once. Batches are paced
    to `tpm_limit` estimated tokens per sliding minute.
    """
    counter = counter or default_counter()
    report = EmbedReport(total=len(items))
    unique: dict[str, str] = {}
    for content_hash, text in items:
        unique.setdefault(content_hash, text)
    found = cache.get_embeddings(provider.model, provider.dimensions, list(unique))
    report.cached = sum(1 for h, _ in items if h in found)
    missing = [(h, t) for h, t in unique.items() if h not in found]
    if max_new is not None and len(missing) > max_new:
        report.stopped = f"--max-embed {max_new} reached"
        missing = missing[:max_new]
    batches = plan_batches(
        missing,
        max_items=max(1, min(batch_size, provider.max_batch)),
        max_tokens=batch_tokens,
        counter=counter,
    )
    window: list[tuple[float, int]] = []
    done = 0
    for index, batch in enumerate(batches):
        size = sum(tokens for _, _, tokens in batch)
        if tpm_limit:
            now = clock()
            window = [(at, n) for at, n in window if now - at < 60.0]
            while window and sum(n for _, n in window) + size > tpm_limit:
                sleep(max(0.0, window[0][0] + 60.0 - now) + 0.5)
                now = clock()
                window = [(at, n) for at, n in window if now - at < 60.0]
        try:
            vectors = provider.embed([text for _, text, _ in batch], "document")
        except EmbeddingError as exc:
            if not exc.daily:
                raise
            # Stop cleanly: everything embedded so far is cached and will be synced; the
            # next run (after the quota resets) continues from here.
            report.stopped = f"daily quota reached: {exc}"
            break
        window.append((clock(), size))
        pairs = list(zip((h for h, _, _ in batch), vectors, strict=True))
        cache.put_embeddings(provider.model, provider.dimensions, pairs)
        found.update(pairs)
        report.batches += 1
        report.embedded += len(batch)
        done += len(batch)
        if on_batch:
            on_batch(done, len(missing))
        if pause_s and index + 1 < len(batches):
            sleep(pause_s)
    report.missing = sum(1 for h in unique if h not in found)
    return found, report
