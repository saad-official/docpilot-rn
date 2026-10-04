"""Postgres + pgvector integration: migrations, idempotent corpus sync, both retrievers.

Runs only with TEST_DATABASE_URL pointing at a disposable database with the `vector`
extension available (CI: the pgvector/pgvector:pg16 service). It drops schema `docpilot`.
"""

import os

import pytest

from docpilot.db.migrate import apply_migrations
from docpilot.db.store import QuestionRecord
from docpilot.ingest.pipeline import ingest

from .conftest import PAGE_V58, FakeEmbedder

pytestmark = pytest.mark.postgres
DSN = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def pg():
    if not DSN:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    from docpilot.db.postgres import PostgresStore

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS docpilot CASCADE")
    assert apply_migrations(DSN, dimensions=64) == ["0001_init.sql"]
    assert apply_migrations(DSN, dimensions=64) == []
    store = PostgresStore(DSN)
    yield store
    store.close()


def test_sync_is_idempotent_and_search_works(pg):
    embedder = FakeEmbedder()
    files = {"docs/pages/versions/v58.0.0/sdk/notifications.mdx": PAGE_V58}
    first = ingest(
        "expo",
        "v58.0.0",
        store=pg,
        embedder=embedder,
        files=files,
        commit_sha="a" * 40,
        tpm_limit=None,
        pause_s=0,
    )
    again = ingest(
        "expo",
        "v58.0.0",
        store=pg,
        embedder=embedder,
        files=files,
        commit_sha="b" * 40,
        tpm_limit=None,
        pause_s=0,
    )
    assert first.db["new"] == first.chunks and again.db["new"] == 0
    assert again.embed_cached == again.chunks and again.embedded == 0
    corpus = pg.list_corpora()[0]
    assert corpus.commit_sha == "b" * 40 and corpus.embedded_count == corpus.chunk_count

    vector = embedder.embed(["schedule a notification immediately"], "query")[0]
    hits = pg.vector_search("expo", ["v58.0.0", "unversioned"], vector, 5)
    assert hits and all(h.version == "v58.0.0" for h in hits)
    text = pg.fulltext_search(
        "expo", ["v58.0.0"], "schedule or notification", "schedulenotificationasync", 5
    )
    assert any("scheduleNotificationAsync" in h.content for h in text)

    changed = {k: v.replace("immediately", "right away") for k, v in files.items()}
    third = ingest(
        "expo",
        "v58.0.0",
        store=pg,
        embedder=embedder,
        files=changed,
        commit_sha="c" * 40,
        tpm_limit=None,
        pause_s=0,
    )
    assert third.db["removed"] == third.db["new"] >= 1


def test_questions_round_trip(pg):
    record = pg.create_question(
        QuestionRecord(sdk="expo", version="v58.0.0", question="q", client_key="k")
    )
    pg.update_question(record.id, status="done", answer="a", citations={"verified": []})
    stored = pg.get_question(record.id)
    assert stored.status == "done" and stored.answer == "a"
    assert pg.set_feedback(record.id, "down") and pg.get_question(record.id).feedback == "down"
    assert pg.get_question("not-a-uuid") is None
