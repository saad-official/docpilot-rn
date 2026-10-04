"""`uv run migrate`: apply db/migrations/*.sql in order, once each.

Plain SQL files and a short runner instead of Alembic: the schema is small, the files are
readable on their own, and there is no ORM to keep in sync. One placeholder,
`{{EMBEDDING_DIMENSIONS}}`, is filled from the environment (default 768) because the vector
column's dimension is a deploy-time choice (docs/decisions/0001-embedding-provider.md).
"""

from __future__ import annotations

import sys
from importlib import resources

import psycopg

from ..config import get_settings


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("docpilot.db") / "migrations"
    return sorted(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in folder.iterdir()
        if entry.name.endswith(".sql")
    )


def render(sql: str, dimensions: int) -> str:
    return sql.replace("{{EMBEDDING_DIMENSIONS}}", str(int(dimensions)))


def apply_migrations(dsn: str, dimensions: int = 768) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn, prepare_threshold=None, autocommit=False) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS docpilot")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS docpilot.schema_migrations (
                   name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"""
        )
        conn.commit()
        done = {row[0] for row in conn.execute("SELECT name FROM docpilot.schema_migrations")}
        for name, sql in migration_files():
            if name in done:
                continue
            with conn.transaction():  # one transaction per file: no half-applied schema
                conn.execute(render(sql, dimensions))
                conn.execute("INSERT INTO docpilot.schema_migrations (name) VALUES (%s)", (name,))
            applied.append(name)
    return applied


def main() -> None:
    settings = get_settings()
    dsn = settings.dsn(direct=True)
    if not dsn:
        print("DATABASE_URL is not set (see .env.example).", file=sys.stderr)
        raise SystemExit(2)
    applied = apply_migrations(dsn, settings.embedding_dimensions)
    print(f"applied: {', '.join(applied)}" if applied else "database is up to date")


if __name__ == "__main__":
    main()
