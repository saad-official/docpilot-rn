"""Persistence: the Store protocol, an in-memory implementation, and Postgres."""

from __future__ import annotations

from ..config import AppSettings
from .store import IngestStore, MemoryStore, QuestionRecord, Store

__all__ = ["IngestStore", "MemoryStore", "QuestionRecord", "Store", "make_store"]


def make_store(settings: AppSettings, *, direct: bool = False) -> Store:
    """Postgres when a database URL is set, otherwise a process-local MemoryStore.

    The memory fallback suits tests and quick local experiments. It is wrong for Vercel
    (instances do not share memory) and empty until something ingests into it.
    """
    dsn = settings.dsn(direct=direct)
    if dsn:
        from .postgres import PostgresStore

        return PostgresStore(dsn)
    return MemoryStore()
