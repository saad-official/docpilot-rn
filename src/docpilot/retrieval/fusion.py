"""Reciprocal rank fusion and the exact-API-name boost.

RRF (Cormack et al., 2009): score(d) = sum over lists L of 1 / (k + rank_L(d)), rank from 1.

Why ranks, not scores: cosine similarity (0.6-0.8 for everything vaguely on topic) and
`ts_rank_cd` (0.01-0.5, unbounded in shape) are on unrelated scales; any weighted sum of
them needs tuning per corpus and breaks when either distribution shifts. Ranks are
comparable by construction. k = 60 (the paper's value) flattens the curve so a document
ranked 1st by one retriever and absent from the other does not automatically beat one
ranked 3rd by both: 1/61 = 0.0164 vs 2 x 1/63 = 0.0317. Agreement wins.

The boost: when the question names an API (`useRouter`, `expo-notifications`), chunks
that contain that exact string get a bonus on the RRF scale - +0.02 in the title or heading
path (a section *about* it), +0.008 in the body (a mention), capped at +0.03 per chunk. For
scale, the gap between rank 1 and rank 10 in one list is 1/61 - 1/70 = 0.0021, so a
heading match can lift a chunk past most single-list rankings, but not past a chunk both
retrievers agree on and that also matches.
"""

from __future__ import annotations

from collections.abc import Sequence

RRF_K = 60
BOOST_HEADING = 0.02
BOOST_BODY = 0.008
BOOST_CAP = 0.03


def rrf(rankings: dict[str, Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    """Fuse ranked id lists. Ids missing from a list contribute nothing for it."""
    scores: dict[str, float] = {}
    for ids in rankings.values():
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def api_boost(api_names: Sequence[str], heading: str, body: str) -> float:
    if not api_names:
        return 0.0
    heading_l, body_l = heading.lower(), body.lower()
    boost = 0.0
    for name in api_names:
        needle = name.lower()
        if needle in heading_l:
            boost += BOOST_HEADING
        elif needle in body_l:
            boost += BOOST_BODY
    return min(boost, BOOST_CAP)


def order(scores: dict[str, float]) -> list[str]:
    """Ids by descending score; ties broken by id so results are deterministic."""
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
