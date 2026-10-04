"""SQL builders for the two retrievers. Pure functions returning (sql, params), so the
statements are unit-tested without a database and executed by db/postgres.py.

Version filter (spec section 4): Expo questions search the chosen SDK version plus the
unversioned guides; React Native has one version, 'current'.
"""

from __future__ import annotations

from typing import Any

S = "docpilot"

COLUMNS = (
    "c.id, c.sdk, c.version, c.title, c.heading_path, c.anchor, c.url, c.kind, c.content, c.tokens"
)


def versions_for(sdk: str, version: str, *, include_shared: bool = True) -> list[str]:
    if sdk == "expo" and include_shared and version != "unversioned":
        return [version, "unversioned"]
    return [version]


def vector_literal(vector: list[float]) -> str:
    """pgvector's text form. Passed as a parameter and cast, so no driver adapter is needed."""
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


def vector_search_sql(
    sdk: str, versions: list[str], query_vector: list[float], limit: int = 40
) -> tuple[str, dict[str, Any]]:
    """Cosine top-k through the HNSW index.

    `<=>` is cosine *distance* (0 = same direction); the score reported is 1 - distance.
    The WHERE filter is applied to the index scan's candidates, so with a selective filter
    plain HNSW can return fewer than `limit` rows; db/postgres.py raises `hnsw.ef_search`
    and turns on pgvector 0.8's iterative scan in the same transaction to prevent that.
    """
    sql = f"""
        SELECT {COLUMNS}, 1 - (c.embedding <=> %(q)s::vector) AS score
        FROM {S}.chunks c
        WHERE c.sdk = %(sdk)s AND c.version = ANY(%(versions)s) AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %(q)s::vector
        LIMIT %(limit)s"""
    return sql, {
        "q": vector_literal(query_vector),
        "sdk": sdk,
        "versions": versions,
        "limit": limit,
    }


def fulltext_search_sql(
    sdk: str, versions: list[str], english: str, simple: str, limit: int = 40
) -> tuple[str, dict[str, Any]]:
    """Postgres full-text over both tsvector columns.

    Rank: `ts_rank` with normalisation 1 (divide by 1 + log(document length)), plus the
    exact-token match on the `simple` column counted double: when the question names an API,
    the chunk containing that exact name is the one to read. Measured on the golden set
    (36 answerable questions, full-text only, 2026-10-05): `ts_rank_cd(.., 32)` scored
    recall@5 0.72 / MRR 0.51, `ts_rank(.., 1)` 0.86 / 0.69. With OR-ed query terms, cover
    density rewards long chunks that happen to repeat common words ("app", "data"); log-length
    normalisation corrects for that without punishing long reference pages as hard as
    dividing by length (normalisation 2: 0.69 / 0.57). Chosen on the golden set itself, so
    treat the gap as optimistic.
    """
    sql = f"""
        WITH q AS (
            SELECT websearch_to_tsquery('english', %(english)s) AS qe,
                   websearch_to_tsquery('simple', %(simple)s) AS qs
        )
        SELECT {COLUMNS},
               ts_rank(c.tsv, q.qe, 1) + 2 * ts_rank(c.tsv_simple, q.qs, 1) AS score
        FROM {S}.chunks c, q
        WHERE c.sdk = %(sdk)s AND c.version = ANY(%(versions)s)
          AND (c.tsv @@ q.qe OR c.tsv_simple @@ q.qs)
        ORDER BY score DESC, c.id
        LIMIT %(limit)s"""
    return sql, {
        "english": english,
        "simple": simple,
        "sdk": sdk,
        "versions": versions,
        "limit": limit,
    }
