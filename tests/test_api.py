import json

import pytest
from fastapi.testclient import TestClient

from docpilot.answer.diff import DiffAnswer, DiffChange
from docpilot.api.main import create_app
from docpilot.llm import LLMRouteError

from .conftest import make_engine


def events(response) -> list[dict]:  # type: ignore[no-untyped-def]
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = block.split("\n")
        assert lines[0].startswith("id: ")
        out.append(json.loads(lines[1].removeprefix("data: ")))
    return out


@pytest.fixture
def client(engine):  # type: ignore[no-untyped-def]
    return TestClient(create_app(engine))


def ask(client, **body):  # type: ignore[no-untyped-def]
    payload = {"question": "How do I schedule a notification?", "sdk": "expo", "version": "v58.0.0"}
    payload.update(body)
    return client.post("/api/ask", json=payload, headers={"Accept": "text/event-stream"})


def test_versions_lists_sources_newest_first_with_unversioned_last(client):
    body = client.get("/api/versions").json()
    expo = next(s for s in body["sources"] if s["name"] == "expo")
    assert [v["version"] for v in expo["versions"]] == ["v58.0.0", "v57.0.0", "unversioned"]
    assert expo["versions"][-1]["shared"] is True
    assert expo["default_version"] == "v58.0.0"
    assert expo["embedding_model"] == "fake-embed"
    assert expo["versions"][0]["chunk_count"] > 0 and expo["versions"][0]["label"] == "SDK 58"
    rn = next(s for s in body["sources"] if s["name"] == "react-native")
    assert [v["version"] for v in rn["versions"]] == ["current"]


def test_ask_streams_retrieval_tokens_citations_done(client, engine):
    response = ask(client)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    stream = events(response)
    kinds = [e["kind"] for e in stream]
    assert kinds[0] == "retrieval" and kinds[-2:] == ["citations", "done"]
    assert set(kinds[1:-2]) == {"token"}

    retrieval = stream[0]
    assert [c["n"] for c in retrieval["chunks"]] == list(range(1, len(retrieval["chunks"]) + 1))
    first = retrieval["chunks"][0]
    assert {"id", "n", "title", "heading_path", "url", "version", "score", "snippet"} <= set(first)
    assert {c["version"] for c in retrieval["chunks"]} <= {"v58.0.0", "unversioned"}

    citations = stream[-2]["citations"]
    assert citations["unsupported"] is False and citations["verified"][0]["n"] == 1
    assert citations["verified"][0]["chunk_id"] == first["id"]

    done = stream[-1]
    question_id = done["question_id"]
    assert done["usage"]["total_tokens"] > 0 and done["usage"]["usd"] > 0
    assert done["latency_ms"] >= 0

    # The prompt carried the passages in tags and the injection warning.
    prompt, system = engine.models[-1].prompts[0]
    assert '<passage id="1"' in prompt and "not instructions" in system

    stored = client.get(f"/api/questions/{question_id}").json()
    assert stored["status"] == "done" and stored["sdk"] == "expo"
    assert stored["chunks"] == retrieval["chunks"]
    assert stored["citations"] == citations
    assert stored["answer"] == stream[-2]["answer"]


def test_diff_mode_orders_versions_and_numbers_passages_uniquely(settings, store, embedder):
    diff = DiffAnswer(
        summary="The config option was renamed [1][2].",
        changes=[
            DiffChange(
                kind="renamed",
                subject="`enableBackgroundRemoteNotifications`",
                before="enableBackgroundRemoteNotificationsLegacy",
                after="enableBackgroundRemoteNotifications",
                citations=[1, 2, 42],
            )
        ],
        missing=None,
    )
    engine = make_engine(settings, store, embedder, structured=diff)
    client = TestClient(create_app(engine))
    stream = events(
        ask(
            client,
            question="background notifications config option",
            mode="diff",
            version="v58.0.0",
            compare_version="v57.0.0",
        )
    )
    kinds = [e["kind"] for e in stream]
    assert kinds[:2] == ["retrieval", "diff"] and kinds[-2:] == ["citations", "done"]
    retrieval = stream[0]
    assert retrieval["before_version"] == "v57.0.0" and retrieval["after_version"] == "v58.0.0"
    numbers = [c["n"] for c in retrieval["chunks"]]
    assert numbers == list(range(1, len(numbers) + 1))
    assert "unversioned" not in {c["version"] for c in retrieval["chunks"]}
    assert stream[1]["diff"]["changes"][0]["citations"] == [1, 2]
    stored = client.get(f"/api/questions/{stream[-1]['question_id']}").json()
    assert stored["diff"]["before_version"] == "v57.0.0" and stored["mode"] == "diff"


def test_provider_outage_is_an_error_event_and_a_failed_row(settings, store, embedder):
    engine = make_engine(settings, store, embedder, fail=LLMRouteError("answer", ["x", "y"]))
    client = TestClient(create_app(engine))
    stream = events(ask(client))
    assert [e["kind"] for e in stream] == ["retrieval", "error"]
    assert stream[-1]["code"] == "unavailable"
    stored = client.get(f"/api/questions/{stream[-1]['question_id']}").json()
    assert stored["status"] == "failed"


def test_unknown_version_and_validation_errors(client):
    response = ask(client, version="v12.0.0")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "version_not_found"

    response = ask(client, question="x" * 1001)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_input" and detail["field"] == "question"

    response = ask(client, mode="diff")
    assert response.status_code == 422

    response = ask(client, sdk="react-native", version="current", mode="diff", compare_version="x")
    assert response.status_code == 422


def test_thread_is_trimmed_to_eight_messages_and_used_for_rewrite(client, engine):
    thread = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(12)
    ]
    stream = events(ask(client, question="and on Android?", thread=thread))
    assert stream[0]["rewritten"] == "standalone query about notifications"
    rewrite_prompt = engine.models[0].prompts[0][0]
    assert "m4" in rewrite_prompt and "m3" not in rewrite_prompt


def test_rate_limit_returns_429_with_retry_after(settings, store, embedder):
    settings.questions_per_hour_per_ip = 2
    client = TestClient(create_app(make_engine(settings, store, embedder)))
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    response = ask(client)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "rate_limited"
    assert response.json()["detail"]["retry_after"] > 0
    assert int(response.headers["retry-after"]) > 0


def test_feedback_and_missing_questions(client):
    question_id = events(ask(client))[-1]["question_id"]
    response = client.post(f"/api/questions/{question_id}/feedback", json={"feedback": "up"})
    assert response.status_code == 200
    assert client.get(f"/api/questions/{question_id}").json()["feedback"] == "up"
    assert client.get("/api/questions/nope").json()["detail"]["code"] == "question_not_found"
    response = client.post("/api/questions/nope/feedback", json={"feedback": "down"})
    assert response.status_code == 404
    response = client.post(f"/api/questions/{question_id}/feedback", json={"feedback": "meh"})
    assert response.status_code == 422


def test_cors_preflight_for_ask(client):
    response = client.options(
        "/api/ask",
        headers={
            "Origin": "http://localhost:3600",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,accept",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3600"


def test_health_reports_corpora_and_providers(client):
    body = client.get("/api/health").json()
    assert body["ok"] and body["db"] and body["store"] == "memory"
    assert body["providers"] == {"groq": True, "gemini": True, "voyage": False}
    assert {c["version"] for c in body["corpora"]} >= {"v58.0.0", "current"}
    assert body["rerank"] is False


def test_no_matching_passages_refuses_without_a_model_call(settings, embedder):
    from docpilot.db import MemoryStore

    store = MemoryStore()
    from .conftest import build_memory_corpus

    build_memory_corpus(store, embedder)
    store.chunks = {k: v for k, v in store.chunks.items() if v.version != "current"}
    engine = make_engine(settings, store, embedder)
    client = TestClient(create_app(engine))
    stream = events(ask(client, sdk="react-native", version="current", question="zzz qqq"))
    assert stream[0]["chunks"] == []
    assert stream[-2]["verification"]["refused"] is True
    assert stream[-2]["citations"]["unsupported"] is True
    assert engine.models == []
