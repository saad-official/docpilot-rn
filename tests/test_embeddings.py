import httpx
import pytest
import respx

from docpilot.embeddings import (
    EmbeddingError,
    GeminiEmbeddings,
    MemoryEmbeddingCache,
    VoyageEmbeddings,
    embed_with_cache,
    l2_normalise,
    plan_batches,
)
from docpilot.tokens import ApproxCounter

from .conftest import FakeEmbedder

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"


def test_cache_hits_skip_the_provider_and_duplicates_embed_once():
    embedder, cache = FakeEmbedder(), MemoryEmbeddingCache()
    items = [("h1", "alpha"), ("h2", "beta"), ("h1", "alpha")]
    vectors, report = embed_with_cache(embedder, cache, items, tpm_limit=None)
    assert set(vectors) == {"h1", "h2"} and report.embedded == 2 and report.cached == 0
    vectors, report = embed_with_cache(embedder, cache, [*items, ("h3", "gamma")], tpm_limit=None)
    assert report.cached == 3 and report.embedded == 1
    assert embedder.calls == [(2, "document"), (1, "document")]


def test_batches_are_bounded_by_count_and_tokens():
    counter = ApproxCounter()
    items = [(f"h{i}", "x" * 400) for i in range(10)]  # 100 tokens each
    by_count = plan_batches(items, max_items=4, max_tokens=None, counter=counter)
    assert [len(b) for b in by_count] == [4, 4, 2]
    by_tokens = plan_batches(items, max_items=100, max_tokens=250, counter=counter)
    assert [len(b) for b in by_tokens] == [2, 2, 2, 2, 2]


def test_tokens_per_minute_pacing_sleeps_before_overflowing():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    items = [(f"h{i}", "x" * 400) for i in range(3)]  # 100 tokens each
    embed_with_cache(
        FakeEmbedder(),
        MemoryEmbeddingCache(),
        items,
        batch_size=1,
        tpm_limit=250,
        counter=ApproxCounter(),
        sleep=sleep,
        clock=lambda: now[0],
    )
    assert len(slept) == 1 and slept[0] == pytest.approx(60.5)


def test_a_crash_mid_run_keeps_finished_batches_in_the_cache():
    class Flaky(FakeEmbedder):
        def embed(self, texts, input_type):  # type: ignore[no-untyped-def]
            if len(self.calls) == 1:
                self.calls.append((len(texts), input_type))
                raise EmbeddingError("boom")
            return super().embed(texts, input_type)

    cache = MemoryEmbeddingCache()
    items = [("a", "one"), ("b", "two")]
    with pytest.raises(EmbeddingError):
        embed_with_cache(Flaky(), cache, items, batch_size=1, tpm_limit=None)
    assert len(cache.data) == 1
    _, report = embed_with_cache(FakeEmbedder(), cache, items, tpm_limit=None)
    assert report.cached == 1 and report.embedded == 1


@respx.mock
def test_gemini_request_shape_normalisation_and_ledger():
    route = respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}]})
    )
    embedder = GeminiEmbeddings("k", dimensions=2, counter=ApproxCounter())
    assert embedder.embed(["hello world!"], "query") == [[0.6, 0.8]]
    body = route.calls[0].request.read().decode().replace(" ", "")
    assert '"taskType":"RETRIEVAL_QUERY"' in body
    assert '"outputDimensionality":2' in body
    assert route.calls[0].request.headers["x-goog-api-key"] == "k"
    record = embedder.ledger.records[0]
    assert record.tokens == 3 and record.tokens_estimated


@respx.mock
def test_gemini_retries_a_429_with_its_retry_delay_then_succeeds():
    respx.post(GEMINI_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": {"details": [{"retryDelay": "7s"}]}}),
            httpx.Response(200, json={"embeddings": [{"values": [1.0]}]}),
        ]
    )
    slept: list[float] = []
    embedder = GeminiEmbeddings("k", dimensions=1, sleep=slept.append, counter=ApproxCounter())
    assert embedder.embed(["a"], "document") == [[1.0]]
    assert slept == [7.5]


@respx.mock
def test_permanent_errors_fail_fast():
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(400, text="bad"))
    embedder = GeminiEmbeddings("k", dimensions=1, sleep=lambda s: None)
    with pytest.raises(EmbeddingError) as info:
        embedder.embed(["a"], "document")
    assert not info.value.transient
    assert embedder.ledger.records[-1].error


@respx.mock
def test_voyage_uses_reported_tokens_and_index_order():
    respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 2.0]},
                    {"index": 0, "embedding": [2.0, 0.0]},
                ],
                "usage": {"total_tokens": 11},
            },
        )
    )
    embedder = VoyageEmbeddings("k", dimensions=2)
    assert embedder.embed(["a", "b"], "document") == [[1.0, 0.0], [0.0, 1.0]]
    assert embedder.ledger.tokens == 11 and not embedder.ledger.records[0].tokens_estimated


def test_l2_normalise_handles_zero():
    assert l2_normalise([0.0, 0.0]) == [0.0, 0.0]
