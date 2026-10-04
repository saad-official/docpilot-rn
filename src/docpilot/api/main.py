"""The HTTP API (spec section 6). OpenAPI at /api/docs.

    uv run uvicorn docpilot.api.main:app --port 7861     (local)
    main.py at the repository root re-exports `app`       (Vercel's Python runtime)

`create_app(engine)` builds the app around any Engine, which is how the tests run the real
routes with a fake retriever store and a fake model. The default `app` builds its Engine
lazily on first use, so importing this module never opens a database connection.

Errors before a stream starts are JSON: `{"detail": {"code", "message", "retry_after"?,
"field"?}}` with codes `invalid_input` (422), `version_not_found` (404),
`question_not_found` (404), `rate_limited` (429, plus a Retry-After header) and
`unavailable` (503). Errors inside a stream are an `error` event (docs/api.md).
"""

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .. import __version__
from ..answer.diff import version_key
from ..config import get_settings
from ..db.store import MemoryStore
from ..engine import Engine
from ..models import utcnow
from ..observability import configure_logging
from ..retrieval.search import RetrievalError
from .ratelimit import TokenBucket, client_ip, client_key
from .schemas import (
    AskRequest,
    CorpusHealth,
    ErrorBody,
    FeedbackRequest,
    Health,
    QuestionView,
    SourceView,
    VersionsResponse,
    VersionView,
)

SOURCE_LABEL = {"expo": "Expo", "react-native": "React Native"}
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    body = ErrorBody(code=code, message=message, **extra)
    headers = {"Retry-After": str(body.retry_after)} if body.retry_after else None
    return HTTPException(
        status_code=status, detail=body.model_dump(mode="json", exclude_none=True), headers=headers
    )


def version_label(sdk: str, version: str) -> str:
    if version == "unversioned":
        return "Guides (all versions)"
    if version == "current":
        return "Current"
    return f"SDK {version.lstrip('v').split('.')[0]}"


def sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """Unnamed SSE messages (`onmessage` / a fetch reader gets them all) with `id:` lines;
    the payload's `kind` says what it is."""
    for seq, event in enumerate(events, start=1):
        yield f"id: {seq}\ndata: {json.dumps(event, default=str)}\n\n"


def question_view(record: Any) -> QuestionView:
    retrieval = record.retrieval or {}
    return QuestionView(
        id=record.id,
        created_at=record.created_at,
        question=record.question,
        sdk=record.sdk,
        version=record.version,
        compare_version=record.compare_version,
        mode=record.mode,
        status=record.status,
        rewritten=record.rewritten,
        answer=record.answer,
        chunks=retrieval.get("chunks", []),
        citations=record.citations
        if isinstance(record.citations, dict)
        else {"verified": record.citations or [], "removed": [], "unsupported": False},
        verification=record.verification or {},
        diff=record.diff,
        usage=record.usage or {},
        latency_ms=record.latency_ms,
        feedback=record.feedback,
        error=record.error,
    )


def create_app(engine: Engine | None = None) -> FastAPI:
    settings = engine.settings if engine else get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="DocPilot RN API",
        version=__version__,
        description=(
            "Version-aware answers over the Expo and React Native docs: hybrid retrieval, "
            "a streamed answer, and citations verified against the retrieved passages."
        ),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.engine = engine
    app.state.bucket = TokenBucket(settings.questions_per_hour_per_ip, 3600.0)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Authorization", "Last-Event-ID"],
        expose_headers=["Retry-After"],
        max_age=600,
    )

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = [str(part) for part in first.get("loc", []) if part != "body"]
        message = str(first.get("msg", "invalid request")).removeprefix("Value error, ")
        body = ErrorBody(
            code="invalid_input",
            message=f"{loc[0]}: {message}" if loc else message,
            field=loc[0] if loc else None,
        )
        return JSONResponse(
            {"detail": body.model_dump(exclude_none=True)},
            status_code=422,
        )

    def get_engine() -> Engine:
        if app.state.engine is None:
            app.state.engine = Engine.from_settings(settings)
        return app.state.engine

    EngineDep = Annotated[Engine, Depends(get_engine)]

    # ------------------------------------------------------------------ meta

    @app.get("/api/health", response_model=Health, tags=["meta"])
    def health(engine: EngineDep) -> Health:
        db = engine.store.ping()
        corpora: list[CorpusHealth] = []
        if db:
            now = utcnow()
            for corpus in engine.store.list_corpora():
                age = (now - corpus.ingested_at).total_seconds() / 86400
                corpora.append(
                    CorpusHealth(
                        sdk=corpus.sdk,
                        version=corpus.version,
                        chunk_count=corpus.chunk_count,
                        embedded_count=corpus.embedded_count,
                        commit_sha=corpus.commit_sha,
                        ingested_at=corpus.ingested_at,
                        age_days=round(age, 2),
                        stale=age > engine.settings.corpus_max_age_days,
                    )
                )
        embedder = engine.embedder
        return Health(
            ok=db and bool(corpora),
            version=__version__,
            db=db,
            store="memory" if isinstance(engine.store, MemoryStore) else "postgres",
            providers={
                name: engine.settings.has_key(name) for name in ("groq", "gemini", "voyage")
            },
            embedding={
                "provider": embedder.provider if embedder else None,
                "model": embedder.model if embedder else None,
                "dimensions": embedder.dimensions if embedder else None,
            },
            rerank=engine.reranker is not None,
            corpora=corpora,
        )

    @app.get(
        "/api/versions",
        response_model=VersionsResponse,
        tags=["meta"],
        responses={503: {"model": ErrorBody}},
    )
    def versions(engine: EngineDep) -> VersionsResponse:
        """Sources and their indexed versions, newest first; `unversioned` (the Expo guides,
        searched together with every SDK version) is listed last with `shared: true`."""
        try:
            corpora = engine.store.list_corpora()
        except Exception as exc:
            raise _error(503, "unavailable", "the corpus database is unreachable") from exc
        sources: list[SourceView] = []
        for name in ("expo", "react-native"):
            mine = [c for c in corpora if c.sdk == name]
            if not mine:
                continue
            mine.sort(
                key=lambda c: (c.version == "unversioned", [-x for x in version_key(c.version)])
            )
            pickable = [c.version for c in mine if c.version != "unversioned"]
            first = mine[0]
            sources.append(
                SourceView(
                    name=name,  # type: ignore[arg-type]
                    label=SOURCE_LABEL[name],
                    repo=first.repo,
                    licence=first.licence,
                    attribution_url=first.attribution_url,
                    embedding_model=first.embedding_model,
                    default_version=pickable[0] if pickable else None,
                    versions=[
                        VersionView(
                            version=c.version,
                            label=version_label(name, c.version),
                            chunk_count=c.chunk_count,
                            document_count=c.document_count,
                            embedded_count=c.embedded_count,
                            commit_sha=c.commit_sha,
                            ingested_at=c.ingested_at,
                            embedding_model=c.embedding_model,
                            dimensions=c.dimensions,
                            shared=c.version == "unversioned",
                        )
                        for c in mine
                    ],
                )
            )
        return VersionsResponse(sources=sources)

    # ------------------------------------------------------------------ ask

    @app.post(
        "/api/ask",
        tags=["ask"],
        responses={
            200: {"content": {"text/event-stream": {}}},
            404: {"model": ErrorBody},
            422: {"model": ErrorBody},
            429: {"model": ErrorBody},
            503: {"model": ErrorBody},
        },
    )
    async def ask(body: AskRequest, request: Request, engine: EngineDep) -> StreamingResponse:
        """Answer a question as Server-Sent Events: `retrieval`, `token`*, (`diff`),
        `citations`, `done` - or `error`. Each message is unnamed with an `id:` line; its
        JSON `kind` field names the event."""
        key = client_key(client_ip(request, engine.settings), engine.settings)
        allowed, wait_s = app.state.bucket.take(key)
        limit = engine.settings.questions_per_hour_per_ip
        try:
            recent = await run_in_threadpool(
                engine.store.count_questions_since, key, utcnow() - timedelta(hours=1)
            )
        except Exception as exc:
            raise _error(503, "unavailable", "the database is unreachable") from exc
        if not allowed or recent >= limit:
            raise _error(
                429,
                "rate_limited",
                f"You can ask {limit} questions per hour. Try again in a few minutes.",
                retry_after=max(1, int(wait_s) or 120),
            )
        try:
            await run_in_threadpool(engine.service.validate, body)
        except RetrievalError as exc:
            if exc.code == "unknown_version":
                raise _error(404, "version_not_found", exc.message, field="version") from exc
            raise _error(503, "unavailable", exc.message) from exc
        except Exception as exc:
            raise _error(503, "unavailable", "the corpus database is unreachable") from exc
        return StreamingResponse(
            sse(engine.service.ask(body, client_key=key)),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    # ------------------------------------------------------------------ questions

    def get_record(engine: Engine, question_id: str):  # type: ignore[no-untyped-def]
        record = engine.store.get_question(question_id)
        if record is None:
            raise _error(404, "question_not_found", "no stored question with that id")
        return record

    @app.get(
        "/api/questions/{question_id}",
        response_model=QuestionView,
        tags=["questions"],
        responses={404: {"model": ErrorBody}},
    )
    def get_question(question_id: str, engine: EngineDep) -> QuestionView:
        return question_view(get_record(engine, question_id))

    @app.post(
        "/api/questions/{question_id}/feedback",
        tags=["questions"],
        responses={404: {"model": ErrorBody}},
    )
    def feedback(question_id: str, body: FeedbackRequest, engine: EngineDep) -> dict[str, str]:
        if not engine.store.set_feedback(question_id, body.feedback):
            raise _error(404, "question_not_found", "no stored question with that id")
        return {"id": question_id, "feedback": body.feedback}

    return app


app = create_app()
