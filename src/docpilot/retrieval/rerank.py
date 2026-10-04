"""Optional cross-encoder rerank with Voyage `rerank-2.5-lite` (when VOYAGE_API_KEY is set).

Bi-encoder embeddings compress query and passage separately into one vector each, so
fine distinctions ("v57 vs v58", "Android only") blur. A cross-encoder reads the query and
each passage *together* and scores the pair: far more accurate, far too slow to run over a
whole corpus, ideal for re-ordering the 40 fused candidates down to 8. Without a key the
RRF order is used (the eval table shows what that costs).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from ..embeddings import EMBEDDING_PRICES

RERANK_MODEL = "rerank-2.5-lite"


@dataclass
class RerankResult:
    order: list[int]  # indexes into the documents passed in, best first
    scores: list[float]  # relevance score per returned index
    tokens: int
    latency_s: float

    @property
    def cost_usd(self) -> float:
        return self.tokens * EMBEDDING_PRICES.get(RERANK_MODEL, 0.0) / 1_000_000


class VoyageReranker:
    url = "https://api.voyageai.com/v1/rerank"
    model = RERANK_MODEL

    def __init__(self, api_key: str, *, client: httpx.Client | None = None, timeout: float = 15.0):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout)

    def rerank(self, query: str, documents: Sequence[str], top_k: int) -> RerankResult:
        started = time.monotonic()
        response = self.client.post(
            self.url,
            json={
                "query": query,
                "documents": list(documents),
                "model": self.model,
                "top_k": top_k,
                "truncation": True,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        body = response.json()
        data = body["data"]
        return RerankResult(
            order=[item["index"] for item in data],
            scores=[float(item["relevance_score"]) for item in data],
            tokens=int(body.get("usage", {}).get("total_tokens", 0)),
            latency_s=time.monotonic() - started,
        )
