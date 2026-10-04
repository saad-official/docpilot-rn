"""Wiring: settings -> store, embedder, reranker, retriever, model routes, answer service.

`Engine.from_settings` is what the API and the eval runner use; tests build an Engine from
fakes directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from llm_kit import Ledger

from .answer.service import AskService
from .config import AppSettings
from .db import make_store
from .embeddings import EmbeddingProvider, make_embedder
from .llm import ChatModel, RoutedLLM
from .observability import export_question
from .retrieval.rerank import VoyageReranker
from .retrieval.search import Config, Retriever
from .routing import Routing, load_routing

log = logging.getLogger(__name__)


@dataclass
class Engine:
    settings: AppSettings
    store: Any
    embedder: EmbeddingProvider | None
    reranker: VoyageReranker | None
    retriever: Retriever
    routing: Routing
    service: AskService

    @classmethod
    def build(
        cls,
        settings: AppSettings,
        *,
        store: Any,
        embedder: EmbeddingProvider | None,
        reranker: VoyageReranker | None = None,
        model_factory: Any = None,
        routing: Routing | None = None,
    ) -> Engine:
        routing = routing or load_routing()
        retriever = Retriever(store, embedder, reranker=reranker)

        def default_models(tier: str, ledger: Ledger) -> ChatModel:
            return RoutedLLM(
                tier,
                routing.tier(tier),
                ledger=ledger,
                retry=routing.retry.policy(),
                settings=settings.llm_settings(),
            )

        def on_finish(question_id: str, ledger: Ledger, metadata: dict[str, Any]) -> None:
            export_question(settings, question_id, ledger, metadata)

        # Without an embedding key the vector half is unavailable: serve full-text only
        # rather than failing every question.
        config: Config = "hybrid_rerank" if embedder is not None else "fulltext"
        service = AskService(
            store=store,
            retriever=retriever,
            model_factory=model_factory or default_models,
            routing=routing,
            config=config,
            context_budget=settings.context_token_budget,
            on_finish=on_finish,
        )
        return cls(settings, store, embedder, reranker, retriever, routing, service)

    @classmethod
    def from_settings(cls, settings: AppSettings) -> Engine:
        store = make_store(settings)
        try:
            embedder: EmbeddingProvider | None = make_embedder(settings, deadline_s=8.0)
        except ValueError as exc:
            log.warning("no embedding provider (%s): serving full-text retrieval only", exc)
            embedder = None
        reranker = None
        if settings.rerank and settings.has_key("voyage"):
            reranker = VoyageReranker(settings.voyage_api_key.get_secret_value())  # type: ignore[union-attr]
        return cls.build(settings, store=store, embedder=embedder, reranker=reranker)
