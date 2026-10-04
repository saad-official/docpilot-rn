import json

import pytest

from docpilot.evals import runner
from docpilot.evals.scorers import (
    answer_metrics,
    matches,
    percentile,
    recall_at,
    reciprocal_rank,
    refusal_correct,
    retrieval_metrics,
)

PAGE = "https://docs.expo.dev/versions/v58.0.0/sdk/sqlite/"


def test_url_matching_page_and_anchor():
    assert matches(PAGE, PAGE + "#usage", "SQLite › Usage")
    assert matches(
        PAGE + "#prepared-statements", PAGE + "#usage", "SQLite › Usage › Prepared statements"
    )
    assert not matches(PAGE + "#prepared-statements", PAGE + "#usage", "SQLite › Usage")
    assert not matches(PAGE, "https://docs.expo.dev/versions/v57.0.0/sdk/sqlite/")
    assert matches("https://reactnative.dev/docs/flatlist", "https://reactnative.dev/docs/FlatList")


def test_recall_and_reciprocal_rank():
    retrieved = [{"url": "https://x/a/"}, {"url": "https://x/b/"}, {"url": PAGE}]
    assert recall_at([PAGE], retrieved, k=5) == 1.0
    assert recall_at([PAGE], retrieved, k=2) == 0.0
    assert reciprocal_rank([PAGE], retrieved) == pytest.approx(1 / 3)
    assert reciprocal_rank(["https://x/c/"], retrieved) == 0.0


def test_percentile_and_refusal_policy():
    assert percentile([1, 2, 3, 4], 50) == 2 and percentile([1, 2, 3, 4], 95) == 4
    assert percentile([], 50) is None
    assert refusal_correct("required", True) and not refusal_correct("required", False)
    assert refusal_correct("forbidden", False) and refusal_correct("either", True) is None


QUESTIONS = [
    {"id": "q1", "sdk": "expo", "expected_urls": [PAGE], "refusal": "forbidden"},
    {"id": "q2", "sdk": "expo", "expected_urls": [], "refusal": "required"},
    {"id": "q3", "sdk": "react-native", "expected_urls": ["https://reactnative.dev/docs/x"]},
]


def test_retrieval_metrics_skip_unanswerable_and_unmeasured():
    results = {
        "q1": {"chunks": [{"url": "https://x/"}, {"url": PAGE}], "latency_ms": 100},
        "q2": {"chunks": [], "latency_ms": 50},
        "q3": {"chunks": [], "error": "partial_vectors"},
    }
    metrics = retrieval_metrics(QUESTIONS, results)
    assert metrics["n"] == 1 and metrics["recall@5"] == 1.0 and metrics["mrr"] == 0.5
    assert metrics["skipped"] == {"partial_vectors": 1}
    assert metrics["retrieval_p50_ms"] == 50


def test_answer_metrics():
    answers = {
        "q1": {
            "verification": {"emitted": 4, "verified": 3, "refused": False},
            "usage": {"usd": 0.001, "served_by": ["openai/gpt-oss-120b"]},
            "latency_ms": 1000,
        },
        "q2": {
            "verification": {"emitted": 0, "verified": 0, "refused": True},
            "usage": {"usd": 0.0005, "served_by": ["gemini-3.5-flash-lite"]},
            "latency_ms": 3000,
        },
        "q3": {"error": "unavailable: busy"},
    }
    metrics = answer_metrics(QUESTIONS, answers)
    assert metrics["citation_precision"] == 0.75
    assert (metrics["refusal_correct"], metrics["refusal_total"]) == (2, 2)
    assert metrics["errors"] == 1 and metrics["usd_per_question"] == pytest.approx(0.00075)
    assert metrics["served_by"] == {"openai/gpt-oss-120b": 1, "gemini-3.5-flash-lite": 1}


def test_recorded_mode_scores_the_committed_fixture(capsys):
    """What CI runs: no database, no keys."""
    runner.main(["--recorded", "--no-write"])
    out = capsys.readouterr().out
    assert "| Config | recall@5 | MRR |" in out
    assert "full-text" in out


def test_golden_set_shape():
    golden = runner.load_golden()
    questions = golden["questions"]
    assert len(questions) == 40
    assert sum(q["sdk"] == "expo" for q in questions) == 30
    assert sum(q["sdk"] == "react-native" for q in questions) == 10
    assert sum(bool(q.get("version_sensitive")) for q in questions) == 8
    assert sum(q["refusal"] == "required" for q in questions) == 4
    assert len({q["id"] for q in questions}) == 40
    for question in questions:
        assert (question["refusal"] == "required") == (not question["expected_urls"])


def test_doc_section_is_replaced_in_place(tmp_path):
    doc = tmp_path / "evals.md"
    doc.write_text(f"# Evals\n\nintro\n\n{runner.START}\nold\n{runner.END}\n\noutro\n")
    runner.write_doc(f"{runner.START}\nnew\n{runner.END}", doc)
    text = doc.read_text()
    assert "new" in text and "old" not in text and "intro" in text and "outro" in text


def test_fixture_merge_is_per_question(tmp_path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"retrieval": {"hybrid": {"a": {"chunks": []}}}}))
    merged = runner.merge_fixture({"retrieval": {"hybrid": {"b": {"chunks": []}}}}, path)
    assert set(merged["retrieval"]["hybrid"]) == {"a", "b"}
