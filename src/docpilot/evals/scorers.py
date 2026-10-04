"""Code-based scorers for the golden set (spec section 7). Pure functions over plain data,
so the same code scores a live run and the recorded fixture CI uses.

    recall@5        share of answerable questions with an expected URL among the top 5
                    retrieved chunks ("success@5": several expected URLs are alternatives)
    MRR             mean of 1 / rank of the first matching chunk (top 10; 0 when absent)
    citation prec.  verified citation markers / emitted markers, over all answers
    refusal         `required` questions must refuse, `forbidden` ones must not; `either`
                    (an older version that lacks the feature) is not scored
    latency         p50 / p95 of end-to-end answer time; retrieval time separately
    cost            mean USD per question at paid rates (llm-kit ledger + embeddings + rerank)

A chunk matches an expected URL when it is on the same page and, if the expected URL has
an anchor, one of the chunk's headings has that anchor.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

from ..ingest.parse import Slugger


def _page(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/").lower()


def _anchor(url: str) -> str | None:
    return url.split("#", 1)[1].lower() if "#" in url else None


def chunk_anchors(url: str, heading_path: str) -> set[str]:
    anchors = {a for a in [_anchor(url)] if a}
    for part in heading_path.split(" › ")[1:]:
        anchors.add(Slugger.base(part))
    return anchors


def matches(expected: str, url: str, heading_path: str = "") -> bool:
    if _page(expected) != _page(url):
        return False
    wanted = _anchor(expected)
    return wanted is None or wanted in chunk_anchors(url, heading_path)


def first_match_rank(expected: Sequence[str], retrieved: Sequence[dict[str, Any]]) -> int | None:
    """1-based rank of the first retrieved chunk matching any expected URL."""
    for rank, chunk in enumerate(retrieved, start=1):
        if any(matches(e, chunk["url"], chunk.get("heading_path", "")) for e in expected):
            return rank
    return None


def recall_at(expected: Sequence[str], retrieved: Sequence[dict[str, Any]], k: int = 5) -> float:
    rank = first_match_rank(expected, retrieved[:k])
    return 1.0 if rank is not None else 0.0


def reciprocal_rank(
    expected: Sequence[str], retrieved: Sequence[dict[str, Any]], k: int = 10
) -> float:
    rank = first_match_rank(expected, retrieved[:k])
    return 1.0 / rank if rank else 0.0


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(q / 100 * len(ordered)) - 1)
    return ordered[index]


def refusal_correct(policy: str, refused: bool) -> bool | None:
    if policy == "required":
        return refused
    if policy == "forbidden":
        return not refused
    return None


def retrieval_metrics(
    questions: Sequence[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """`results[qid] = {"chunks": [{url, heading_path}...], "latency_ms": float}`."""
    recalls, rrs, latencies = [], [], []
    per_question: dict[str, dict[str, Any]] = {}
    skipped: dict[str, int] = {}
    for question in questions:
        result = results.get(question["id"])
        if result is None:
            continue
        if result.get("error"):  # e.g. vectors not complete for this corpus yet
            skipped[result["error"]] = skipped.get(result["error"], 0) + 1
            continue
        latencies.append(result.get("latency_ms", 0.0))
        if not question["expected_urls"]:
            continue
        r5 = recall_at(question["expected_urls"], result["chunks"])
        rr = reciprocal_rank(question["expected_urls"], result["chunks"])
        recalls.append(r5)
        rrs.append(rr)
        per_question[question["id"]] = {"recall@5": r5, "rr": rr}
    return {
        "n": len(recalls),
        "recall@5": round(statistics.mean(recalls), 4) if recalls else None,
        "mrr": round(statistics.mean(rrs), 4) if rrs else None,
        "retrieval_p50_ms": percentile(latencies, 50),
        "retrieval_p95_ms": percentile(latencies, 95),
        "skipped": skipped,
        "per_question": per_question,
    }


def answer_metrics(
    questions: Sequence[dict[str, Any]], answers: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """`answers[qid] = {"verification": {...}, "usage": {"usd"}, "latency_ms", "error"?}`."""
    emitted = verified = 0
    refusal_hits = refusal_total = 0
    latencies, costs = [], []
    errors = 0
    served: dict[str, int] = {}
    for question in questions:
        answer = answers.get(question["id"])
        if answer is None:
            continue
        if answer.get("error"):
            errors += 1
            continue
        verification = answer.get("verification", {})
        emitted += verification.get("emitted", 0)
        verified += verification.get("verified", 0)
        verdict = refusal_correct(
            question.get("refusal", "forbidden"), verification.get("refused", False)
        )
        if verdict is not None:
            refusal_total += 1
            refusal_hits += int(verdict)
        latencies.append(answer.get("latency_ms", 0))
        costs.append(answer.get("usage", {}).get("usd", 0.0))
        for model in answer.get("usage", {}).get("served_by", []):
            served[model] = served.get(model, 0) + 1
    return {
        "answers": len(latencies),
        "errors": errors,
        "citation_precision": round(verified / emitted, 4) if emitted else None,
        "citations_emitted": emitted,
        "citations_verified": verified,
        "refusal_correct": refusal_hits,
        "refusal_total": refusal_total,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "usd_per_question": round(statistics.mean(costs), 6) if costs else None,
        "usd_total": round(sum(costs), 6),
        "served_by": served,
    }
