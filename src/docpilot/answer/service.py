"""One question, end to end, as a stream of events.

    question (+ thread) -> rewrite? -> retrieve -> [retrieval] -> generate -> [token]*
                        -> verify citations -> [citations] -> store -> [done]
    diff mode:  retrieve(older) + retrieve(newer) -> [retrieval] -> structured DiffAnswer
                -> [diff] -> prose rendered by code -> [token]* -> [citations] -> [done]

Every event is a dict with a `kind`. The service is synchronous (llm-kit is) and is
iterated by the API in a worker thread. The question row is written *before* the first
event (status `pending`) and completed at the end, so a share link works even for a
stream the browser abandoned, and a failure is recorded rather than lost.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

from llm_kit import Ledger, LLMBudgetError, LLMError

from ..api.schemas import AskRequest
from ..db.store import QuestionRecord
from ..embeddings import EMBEDDING_PRICES
from ..llm import ChatModel, LLMRouteError, LLMStreamInterrupted, usage_summary
from ..models import RetrievedChunk
from ..prompts import load_prompt, render
from ..retrieval.context import Passage, assemble, render_passages
from ..retrieval.search import Config, RetrievalError, RetrievalResult, Retriever
from ..routing import Routing
from ..tokens import default_counter
from .diff import DiffAnswer, clean_diff, order_versions, render_diff
from .verify import verify_answer

log = logging.getLogger(__name__)

Event = dict[str, Any]
ModelFactory = Callable[[str, Ledger], ChatModel]

SDK_LABEL = {"expo": "Expo", "react-native": "React Native"}


def version_label(sdk: str, version: str) -> str:
    if sdk == "react-native":
        return "React Native (current docs)"
    if version == "unversioned":
        return "Expo (all versions)"
    major = version.lstrip("v").split(".")[0]
    return f"Expo SDK {major} ({version})"


def refusal_text(sdk: str, version: str) -> str:
    return (
        f"I couldn't find this in the {SDK_LABEL[sdk]} docs for {version_label(sdk, version)}. "
        "No passage matched the question; try naming the API or the guide you mean."
    )


def chunk_view(passage: Passage) -> dict[str, Any]:
    """The retrieval-event shape: `n` is the number the answer cites; `snippet` is the full
    passage text the model saw and the verifier checked."""
    chunk = passage.chunk
    return {
        "n": passage.n,
        "id": chunk.id,
        "sdk": chunk.sdk,
        "version": chunk.version,
        "title": chunk.title,
        "heading_path": chunk.heading_path,
        "url": chunk.url,
        "kind": chunk.kind,
        "score": chunk.score,
        "scores": chunk.scores,
        "snippet": chunk.content,
    }


def _trace(result: RetrievalResult) -> dict[str, Any]:
    return {
        "config": result.config,
        "effective_config": result.effective_config,
        "query": result.query,
        "versions": result.versions,
        "api_names": result.api_names,
        "trace": result.trace,
        "timings_ms": result.timings_ms,
    }


class AskService:
    def __init__(
        self,
        *,
        store: Any,
        retriever: Retriever,
        model_factory: ModelFactory,
        routing: Routing,
        config: Config = "hybrid_rerank",
        context_budget: int = 6000,
        on_finish: Callable[[str, Ledger, dict[str, Any]], None] | None = None,
    ):
        self.store = store
        self.retriever = retriever
        self.model_factory = model_factory
        self.routing = routing
        self.config = config
        self.context_budget = context_budget
        self.on_finish = on_finish
        self.counter = default_counter()

    # ------------------------------------------------------------------ checks

    def validate(self, request: AskRequest) -> None:
        """Raise RetrievalError before any streaming when a version is unknown."""
        self.retriever.check(request.sdk, request.version)
        if request.mode == "diff" and request.compare_version:
            self.retriever.check(request.sdk, request.compare_version)

    # ------------------------------------------------------------------ steps

    def _rewrite(self, request: AskRequest, ledger: Ledger) -> str | None:
        if not request.thread:
            return None
        template, _ = load_prompt("rewrite", self.routing.prompts.get("rewrite", "v1"))
        system = render(template, sdk_label=SDK_LABEL[request.sdk])
        history = "\n".join(f"{m.role}: {m.content[:1500]}" for m in request.thread)
        model = self.model_factory("rewrite", ledger)
        try:
            text = model.complete(
                f"Conversation so far:\n{history}\n\nLatest message: {request.question}",
                system=system,
            )
        except LLMError as exc:  # optional step: fall back to the raw question
            log.warning("query rewrite failed: %s", exc)
            return None
        line = text.strip().splitlines()[0].strip().strip('"') if text.strip() else ""
        return line[:500] or None

    def _query_cost(self, query: str) -> tuple[int, float]:
        embedder = self.retriever.embedder
        if embedder is None:
            return 0, 0.0
        tokens = self.counter.count(query)
        return tokens, tokens * EMBEDDING_PRICES.get(embedder.model, 0.0) / 1_000_000

    # ------------------------------------------------------------------ the stream

    def ask(self, request: AskRequest, *, client_key: str | None = None) -> Iterator[Event]:
        started = time.monotonic()
        record = QuestionRecord(
            sdk=request.sdk,
            version=request.version,
            compare_version=request.compare_version if request.mode == "diff" else None,
            mode=request.mode,
            question=request.question,
            client_key=client_key,
        )
        self.store.create_question(record)
        ledger = Ledger(max_usd=self.routing.budget.max_usd_per_question)
        served: list[str] = []
        extra_usd = 0.0
        stage = "retrieval"
        try:
            rewritten = self._rewrite(request, ledger)
            query = rewritten or request.question
            _, usd = self._query_cost(query)
            extra_usd += usd * (2 if request.mode == "diff" else 1)

            if request.mode == "diff":
                yield from self._diff(
                    request, query, record, ledger, served, started, rewritten, extra_usd
                )
                return

            result = self.retriever.retrieve(
                query, sdk=request.sdk, version=request.version, config=self.config
            )
            extra_usd += result.rerank_usd
            passages = assemble(result.chunks, budget_tokens=self.context_budget)
            views = [chunk_view(p) for p in passages]
            retrieval = {**_trace(result), "chunks": views}
            self.store.update_question(record.id, rewritten=rewritten, retrieval=retrieval)
            yield {
                "kind": "retrieval",
                "question_id": record.id,
                "rewritten": rewritten,
                "config": result.effective_config,
                "versions": result.versions,
                "chunks": views,
            }

            stage = "generation"
            if passages:
                template, prompt_id = load_prompt(
                    "answer", self.routing.prompts.get("answer", "v1")
                )
                system = render(
                    template,
                    sdk_label=SDK_LABEL[request.sdk],
                    version_label=version_label(request.sdk, request.version),
                )
                user = (
                    f"{render_passages(passages)}\n\n"
                    f"Question ({version_label(request.sdk, request.version)}): "
                    f"{request.question}"
                )
                if rewritten:
                    user += f"\n(Search query used: {rewritten})"
                model = self.model_factory("answer", ledger)
                parts: list[str] = []
                for piece in model.stream(user, system=system):
                    parts.append(piece)
                    yield {"kind": "token", "text": piece}
                served = model.served_by
                text = "".join(parts)
            else:
                prompt_id = None
                text = refusal_text(request.sdk, request.version)
                yield {"kind": "token", "text": text}

            stage = "verification"
            checked = verify_answer(text, passages)
            yield {
                "kind": "citations",
                "citations": checked.citations_payload(),
                "answer": checked.answer,
                "verification": checked.verification.model_dump(),
            }
            yield self._finish(
                record,
                ledger,
                served,
                started,
                extra_usd,
                answer=checked.answer,
                citations=checked.citations_payload(),
                verification={**checked.verification.model_dump(), "prompt": prompt_id},
            )
        except Exception as exc:  # every failure becomes an `error` event and a failed row
            yield self._fail(record, ledger, served, started, extra_usd, stage, exc)

    def _diff(
        self,
        request: AskRequest,
        query: str,
        record: QuestionRecord,
        ledger: Ledger,
        served: list[str],
        started: float,
        rewritten: str | None,
        extra_usd: float = 0.0,
    ) -> Iterator[Event]:
        assert request.compare_version
        older, newer = order_versions(request.version, request.compare_version)
        # Version differences live in the versioned reference; the unversioned guides are
        # identical for both sides, so they are left out of a diff.
        before = self.retriever.retrieve(
            query, sdk=request.sdk, version=older, config=self.config, include_shared=False
        )
        after = self.retriever.retrieve(
            query, sdk=request.sdk, version=newer, config=self.config, include_shared=False
        )
        extra_usd += before.rerank_usd + after.rerank_usd
        half = self.context_budget // 2
        passages_before = assemble(before.chunks, budget_tokens=half, top_n=5)
        passages_after = assemble(
            after.chunks, budget_tokens=half, top_n=5, start=len(passages_before) + 1
        )
        passages = passages_before + passages_after
        views = [chunk_view(p) for p in passages]
        retrieval = {
            "before": _trace(before),
            "after": _trace(after),
            "older": older,
            "newer": newer,
            "chunks": views,
        }
        self.store.update_question(record.id, rewritten=rewritten, retrieval=retrieval)
        yield {
            "kind": "retrieval",
            "question_id": record.id,
            "rewritten": rewritten,
            "config": after.effective_config,
            "versions": [older, newer],
            "before_version": older,
            "after_version": newer,
            "chunks": views,
        }
        before_label = version_label(request.sdk, older)
        after_label = version_label(request.sdk, newer)
        template, prompt_id = load_prompt("diff", self.routing.prompts.get("diff", "v1"))
        system = render(
            template,
            sdk_label=SDK_LABEL[request.sdk],
            before_label=before_label,
            after_label=after_label,
        )
        user = f"{render_passages(passages)}\n\nQuestion: {request.question}"
        model = self.model_factory("diff", ledger)
        if passages:
            diff = model.complete_structured(user, DiffAnswer, system=system)
            served.extend(model.served_by)
        else:
            diff = DiffAnswer(
                summary=refusal_text(request.sdk, newer), changes=[], missing="No passages."
            )
        diff, dropped = clean_diff(diff, [p.n for p in passages])
        diff_payload = {**diff.model_dump(), "before_version": older, "after_version": newer}
        yield {"kind": "diff", "diff": diff_payload, "dropped_changes": dropped}
        prose = render_diff(diff, before_label, after_label)
        for line in prose.splitlines(keepends=True):
            yield {"kind": "token", "text": line}
        checked = verify_answer(prose, passages)
        yield {
            "kind": "citations",
            "citations": checked.citations_payload(),
            "answer": checked.answer,
            "verification": checked.verification.model_dump(),
        }
        yield self._finish(
            record,
            ledger,
            served,
            started,
            extra_usd,
            answer=checked.answer,
            citations=checked.citations_payload(),
            verification={
                **checked.verification.model_dump(),
                "dropped_changes": dropped,
                "prompt": prompt_id,
            },
            diff=diff_payload,
        )

    # ------------------------------------------------------------------ endings

    def _usage(self, ledger: Ledger, served: list[str], extra_usd: float) -> dict[str, Any]:
        usage = usage_summary(ledger, served)
        usage["llm_usd"] = usage["usd"]
        usage["retrieval_usd"] = round(extra_usd, 8)
        usage["usd"] = round(usage["usd"] + extra_usd, 8)
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return usage

    def _finish(
        self,
        record: QuestionRecord,
        ledger: Ledger,
        served: list[str],
        started: float,
        extra_usd: float,
        **fields: Any,
    ) -> Event:
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = self._usage(ledger, served, extra_usd)
        self.store.update_question(
            record.id, status="done", usage=usage, latency_ms=latency_ms, **fields
        )
        if self.on_finish:
            self.on_finish(record.id, ledger, {"mode": record.mode, "sdk": record.sdk})
        return {"kind": "done", "question_id": record.id, "latency_ms": latency_ms, "usage": usage}

    def _fail(
        self,
        record: QuestionRecord,
        ledger: Ledger,
        served: list[str],
        started: float,
        extra_usd: float,
        stage: str,
        exc: Exception,
    ) -> Event:
        if isinstance(exc, RetrievalError):
            code = "version_not_found" if exc.code == "unknown_version" else "unavailable"
            message = exc.message
        elif isinstance(exc, LLMBudgetError):
            code, message = "unavailable", "This question hit its cost ceiling."
        elif isinstance(exc, LLMStreamInterrupted):
            code, message = "stream", "The model stopped mid-answer. Ask again."
        elif isinstance(exc, LLMRouteError | LLMError):
            code = "unavailable"
            message = "Every model provider is busy or rate-limited right now. Try again soon."
        else:
            code, message = "server", f"Something failed during {stage}."
        log.exception("question %s failed during %s", record.id, stage, exc_info=exc)
        try:
            self.store.update_question(
                record.id,
                status="failed",
                error=f"{stage}: {type(exc).__name__}: {str(exc)[:500]}",
                usage=self._usage(ledger, served, extra_usd),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception:
            log.exception("could not record the failure of question %s", record.id)
        return {"kind": "error", "code": code, "message": message, "question_id": record.id}


def passages_from_chunks(chunks: list[RetrievedChunk]) -> list[Passage]:
    return [Passage(n=i, chunk=c) for i, c in enumerate(chunks, start=1)]
