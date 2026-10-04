"""PostgresStore: the Store and IngestStore protocols over psycopg 3 and a small pool.

`prepare_threshold=None` because Neon's pooled endpoint is PgBouncer in transaction mode,
which breaks server-side prepared statements. Vectors travel as pgvector's text form
(`'[0.1,0.2,...]'::vector`), so no extra adapter package is needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..models import Chunk, CorpusInfo, DocumentRecord, RetrievedChunk
from ..retrieval.sql import fulltext_search_sql, vector_literal, vector_search_sql
from .store import QUESTION_UPDATABLE, QuestionRecord

S = "docpilot"
_JSON_FIELDS = {"retrieval", "citations", "verification", "diff", "usage"}
# HNSW candidate list size. pgvector's default (40) equals our top-k, so any filtered-out
# candidate shortens the result; 100 plus iterative scan keeps 40 rows coming.
EF_SEARCH = 100


def _parse_vector(text: str) -> list[float]:
    return [float(v) for v in text.strip("[]").split(",") if v]


class PostgresStore:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 4):
        self.pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"prepare_threshold": None, "row_factory": dict_row},
        )
        self.pool.open(wait=False)

    def close(self) -> None:
        self.pool.close()

    def _execute(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall()) if cur.description else []

    # -- read side -------------------------------------------------------------------
    def ping(self) -> bool:
        try:
            self._execute("SELECT 1")
            return True
        except Exception:
            return False

    def list_corpora(self) -> list[CorpusInfo]:
        rows = self._execute(
            f"""SELECT c.id, s.name AS sdk, c.version, s.repo, s.licence, s.attribution_url,
                       c.commit_sha, c.embedding_model, c.dimensions, c.chunk_count,
                       c.document_count, c.ingested_at, c.stats,
                       (SELECT count(*) FROM {S}.chunks k
                        WHERE k.corpus_id = c.id AND k.embedding IS NOT NULL) AS embedded_count
                FROM {S}.corpora c JOIN {S}.sources s ON s.id = c.source_id
                ORDER BY s.name, c.version DESC"""
        )
        return [CorpusInfo(**row) for row in rows]

    @staticmethod
    def _chunks(rows: list[dict[str, Any]]) -> list[RetrievedChunk]:
        return [RetrievedChunk(**{**row, "score": float(row["score"])}) for row in rows]

    def vector_search(
        self, sdk: str, versions: list[str], vector: list[float], limit: int
    ) -> list[RetrievedChunk]:
        sql, params = vector_search_sql(sdk, versions, vector, limit)
        with self.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            # SET LOCAL lasts for this transaction only, which is what PgBouncer's
            # transaction pooling requires.
            cur.execute(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}")
            try:
                with conn.transaction():
                    cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            except Exception:
                pass  # pgvector < 0.8: ef_search alone
            cur.execute(sql, params)
            return self._chunks(list(cur.fetchall()))

    def fulltext_search(
        self, sdk: str, versions: list[str], english: str, simple: str, limit: int
    ) -> list[RetrievedChunk]:
        sql, params = fulltext_search_sql(sdk, versions, english, simple, limit)
        return self._chunks(self._execute(sql, params))

    # -- questions -------------------------------------------------------------------------
    def create_question(self, record: QuestionRecord) -> QuestionRecord:
        data = record.model_dump()
        columns = list(data)
        values = [
            Jsonb(data[c]) if c in _JSON_FIELDS and data[c] is not None else data[c]
            for c in columns
        ]
        self._execute(
            f"INSERT INTO {S}.questions ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            values,
        )
        return record

    def update_question(self, question_id: str, **fields: Any) -> None:
        unknown = set(fields) - QUESTION_UPDATABLE
        if unknown:
            raise ValueError(f"not updatable question fields: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{column} = %s" for column in fields)
        values = [Jsonb(v) if c in _JSON_FIELDS and v is not None else v for c, v in fields.items()]
        self._execute(
            f"UPDATE {S}.questions SET {assignments} WHERE id = %s", (*values, question_id)
        )

    def get_question(self, question_id: str) -> QuestionRecord | None:
        try:
            rows = self._execute(f"SELECT * FROM {S}.questions WHERE id = %s", (question_id,))
        except Exception:  # not a uuid
            return None
        if not rows:
            return None
        row = dict(rows[0])
        row["id"] = str(row["id"])
        return QuestionRecord(**row)

    def set_feedback(self, question_id: str, feedback: str) -> bool:
        try:
            rows = self._execute(
                f"UPDATE {S}.questions SET feedback = %s WHERE id = %s RETURNING id",
                (feedback, question_id),
            )
        except Exception:
            return False
        return bool(rows)

    def count_questions_since(self, client_key: str, since: datetime) -> int:
        rows = self._execute(
            f"SELECT count(*) AS n FROM {S}.questions WHERE client_key = %s AND created_at >= %s",
            (client_key, since),
        )
        return int(rows[0]["n"])

    def put_eval_run(
        self, golden_version: str, config: dict[str, Any], metrics: dict[str, Any]
    ) -> str:
        from uuid import uuid4

        eval_id = str(uuid4())
        self._execute(
            f"INSERT INTO {S}.eval_runs (id, golden_version, config, metrics) "
            "VALUES (%s, %s, %s, %s)",
            (eval_id, golden_version, Jsonb(config), Jsonb(metrics)),
        )
        return eval_id

    # -- ingestion -----------------------------------------------------------------------
    def get_embeddings(
        self, model: str, dimensions: int, hashes: list[str]
    ) -> dict[str, list[float]]:
        if not hashes:
            return {}
        found: dict[str, list[float]] = {}
        for start in range(0, len(hashes), 500):
            rows = self._execute(
                f"""SELECT content_hash, embedding::text AS embedding
                    FROM {S}.embedding_cache
                    WHERE model = %s AND dimensions = %s AND content_hash = ANY(%s)""",
                (model, dimensions, hashes[start : start + 500]),
            )
            found.update({r["content_hash"]: _parse_vector(r["embedding"]) for r in rows})
        return found

    def put_embeddings(
        self, model: str, dimensions: int, items: list[tuple[str, list[float]]]
    ) -> None:
        if not items:
            return
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                f"""INSERT INTO {S}.embedding_cache (content_hash, model, dimensions, embedding)
                    VALUES (%s, %s, %s, %s::vector)
                    ON CONFLICT (content_hash, model, dimensions) DO NOTHING""",
                [(h, model, dimensions, vector_literal(v)) for h, v in items],
            )

    def sync_corpus(
        self,
        *,
        sdk: str,
        repo: str,
        licence: str,
        attribution_url: str,
        version: str,
        commit_sha: str,
        embedding_model: str,
        dimensions: int,
        documents: list[DocumentRecord],
        chunks: list[Chunk],
        embeddings: dict[str, list[float]],
        stats: dict[str, Any],
    ) -> dict[str, int]:
        """Idempotent replace of one corpus, in one transaction.

        Chunk ids are content-derived, so an unchanged chunk keeps its id across re-ingests
        (stored question traces stay meaningful); rows that no longer exist upstream are
        deleted. Either the whole corpus switches to the new commit or nothing changes.
        """
        with self.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {S}.sources (name, repo, licence, attribution_url)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET repo = EXCLUDED.repo,
                        licence = EXCLUDED.licence, attribution_url = EXCLUDED.attribution_url
                    RETURNING id""",
                (sdk, repo, licence, attribution_url),
            )
            source_id = cur.fetchone()["id"]
            cur.execute(
                f"SELECT id, embedding_model, dimensions FROM {S}.corpora "
                "WHERE source_id = %s AND version = %s",
                (source_id, version),
            )
            existing = cur.fetchone()
            if existing and (
                existing["embedding_model"] != embedding_model
                or existing["dimensions"] != dimensions
            ):
                raise ValueError(
                    f"corpus {sdk}@{version} is embedded with {existing['embedding_model']} "
                    f"({existing['dimensions']}-d); re-embedding with {embedding_model} "
                    f"({dimensions}-d) needs the procedure in docs/setup.md"
                )
            cur.execute(
                f"""INSERT INTO {S}.corpora (source_id, version, commit_sha, embedding_model,
                        dimensions, chunk_count, document_count, stats, ingested_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (source_id, version) DO UPDATE SET
                        commit_sha = EXCLUDED.commit_sha, chunk_count = EXCLUDED.chunk_count,
                        document_count = EXCLUDED.document_count, stats = EXCLUDED.stats,
                        ingested_at = now()
                    RETURNING id""",
                (
                    source_id,
                    version,
                    commit_sha,
                    embedding_model,
                    dimensions,
                    len(chunks),
                    len(documents),
                    Jsonb(stats),
                ),
            )
            corpus_id = cur.fetchone()["id"]
            cur.execute(f"SELECT id FROM {S}.chunks WHERE corpus_id = %s", (corpus_id,))
            old_ids = {row["id"] for row in cur.fetchall()}
            new_ids = {c.id for c in chunks}
            doc_ids = [d.id for d in documents]
            cur.execute(
                f"DELETE FROM {S}.chunks WHERE corpus_id = %s AND NOT (id = ANY(%s))",
                (corpus_id, list(new_ids)),
            )
            cur.execute(
                f"DELETE FROM {S}.documents WHERE corpus_id = %s AND NOT (id = ANY(%s))",
                (corpus_id, doc_ids),
            )
            cur.executemany(
                f"""INSERT INTO {S}.documents (id, corpus_id, path, url, title, description,
                        platforms, content_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET url = EXCLUDED.url, title = EXCLUDED.title,
                        description = EXCLUDED.description, platforms = EXCLUDED.platforms,
                        content_hash = EXCLUDED.content_hash""",
                [
                    (
                        d.id,
                        corpus_id,
                        d.path,
                        d.url,
                        d.title,
                        d.description,
                        d.platforms,
                        d.content_hash,
                    )
                    for d in documents
                ],
            )
            # Unchanged chunks (same id = same content) are skipped; only new ones are
            # written, which keeps a no-op re-ingest to a few hundred milliseconds of SQL.
            fresh = [c for c in chunks if c.id not in old_ids]
            cur.executemany(
                f"""INSERT INTO {S}.chunks (id, document_id, corpus_id, sdk, version, ordinal,
                        title, heading_path, anchor, url, kind, content, tokens, content_hash,
                        embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (id) DO NOTHING""",
                [
                    (
                        c.id,
                        c.document_id,
                        corpus_id,
                        c.sdk,
                        c.version,
                        c.ordinal,
                        c.title,
                        c.heading_path,
                        c.anchor,
                        c.url,
                        c.kind,
                        c.content,
                        c.tokens,
                        c.content_hash,
                        vector_literal(embeddings[c.content_hash])
                        if c.content_hash in embeddings
                        else None,
                    )
                    for c in fresh
                ],
            )
            # Chunks stored without a vector on an earlier, quota-limited run get theirs from
            # the cache as soon as it has them.
            cur.execute(
                f"""UPDATE {S}.chunks c SET embedding = e.embedding
                    FROM {S}.embedding_cache e
                    WHERE c.corpus_id = %s AND c.embedding IS NULL
                      AND e.content_hash = c.content_hash AND e.model = %s
                      AND e.dimensions = %s""",
                (corpus_id, embedding_model, dimensions),
            )
            cur.execute(
                f"SELECT count(*) AS n FROM {S}.chunks "
                "WHERE corpus_id = %s AND embedding IS NOT NULL",
                (corpus_id,),
            )
            embedded = cur.fetchone()["n"]
            # Ordinals can shift when a page gains a section above an unchanged chunk.
            cur.executemany(
                f"UPDATE {S}.chunks SET ordinal = %s WHERE id = %s AND ordinal <> %s",
                [(c.ordinal, c.id, c.ordinal) for c in chunks if c.id in old_ids],
            )
        return {
            "upserted": len(new_ids),
            "removed": len(old_ids - new_ids),
            "new": len(new_ids - old_ids),
            "embedded": int(embedded),
        }
