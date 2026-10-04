"""Ingestion: fetch -> parse -> chunk -> embed (cached) -> idempotent upsert.

    uv run ingest expo --version v58.0.0
    uv run ingest expo --version unversioned
    uv run ingest react-native --version current

Runs offline from the API (locally or in GitHub Actions), never from the web.
"""

from __future__ import annotations

import logging
import posixpath
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..embeddings import EMBEDDING_PRICES, EmbeddingProvider, embed_with_cache
from ..models import Chunk, DocumentRecord
from ..tokens import TokenCounter, default_counter
from .chunker import MAX_TOKENS, chunk_page, document_id, sha256
from .fetch import FetchMode, fetch_docs, resolve_commit
from .parse import parse_page
from .sources import SOURCES, SourceSpec, validate_version

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    sdk: str
    version: str
    repo: str
    commit_sha: str
    fetch_mode: str
    files: int = 0
    documents: int = 0
    skipped_empty: int = 0
    chunks: int = 0
    chunks_by_kind: dict[str, int] = field(default_factory=dict)
    tokens: int = 0
    avg_tokens: float = 0.0
    oversized_chunks: int = 0  # atomic code/table blocks above MAX_TOKENS
    embedded: int = 0
    embed_cached: int = 0
    embed_batches: int = 0
    # Chunks still without a vector (daily quota or --max-embed). They are stored and
    # searchable by full-text now; re-running the same command embeds them from the cache.
    embed_missing: int = 0
    embed_stopped: str | None = None
    embedding_model: str = ""
    dimensions: int = 0
    embedding_tokens: int = 0
    embedding_usd: float = 0.0
    embedding_usd_full_corpus: float = 0.0  # what embedding everything from scratch costs
    db: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(self.chunks_by_kind.items()))
        lines = [
            f"{self.sdk}@{self.version}  {self.repo}@{self.commit_sha[:10]}  ({self.fetch_mode})",
            f"  files {self.files}  documents {self.documents}  empty skipped {self.skipped_empty}",
            f"  chunks {self.chunks} ({kinds})  tokens {self.tokens}  avg {self.avg_tokens:.0f}"
            f"  oversized atomic blocks {self.oversized_chunks}",
            f"  embeddings {self.embedding_model} {self.dimensions}-d: {self.embedded} new, "
            f"{self.embed_cached} cached, {self.embed_batches} calls, "
            f"{self.embedding_tokens} tokens, ${self.embedding_usd:.6f} at paid rates "
            f"(full corpus from scratch: ${self.embedding_usd_full_corpus:.6f})",
        ]
        if self.embed_missing:
            lines.append(
                f"  PARTIAL: {self.embed_missing} chunks have no vector yet "
                f"({self.embed_stopped}); re-run to continue"
            )
        if self.db:
            lines.append(
                f"  database: {self.db.get('upserted', 0)} chunks live, "
                f"{self.db.get('new', 0)} new, {self.db.get('removed', 0)} removed, "
                f"{self.db.get('embedded', 0)} with vectors"
            )
        lines.append(f"  elapsed {self.elapsed_s:.1f}s{'  (dry run)' if self.dry_run else ''}")
        return "\n".join(lines)


def build_corpus(
    spec: SourceSpec,
    version: str,
    files: dict[str, str],
    counter: TokenCounter | None = None,
    limit: int | None = None,
) -> tuple[list[DocumentRecord], list[Chunk], int]:
    """Parse and chunk fetched files. Returns (documents, chunks, empty pages skipped)."""
    counter = counter or default_counter()
    prefix = spec.prefix(version)
    rel_files = {path[len(prefix) :]: text for path, text in files.items()}

    def resolver_for(rel: str) -> Callable[[str], str | None]:
        base = posixpath.dirname(rel)
        return lambda target: rel_files.get(posixpath.normpath(posixpath.join(base, target)))

    documents: list[DocumentRecord] = []
    chunks: list[Chunk] = []
    skipped = 0
    pages = sorted(rel for rel in rel_files if not spec.is_partial(rel))
    if limit:
        pages = pages[:limit]
    for rel in pages:
        raw = rel_files[rel]
        page = parse_page(rel, raw, resolve_partial=resolver_for(rel))
        if not page.sections:
            skipped += 1
            continue
        url = spec.page_url(version, rel, page.frontmatter)
        page_chunks = chunk_page(page, sdk=spec.sdk, version=version, url=url, counter=counter)
        if not page_chunks:
            skipped += 1
            continue
        documents.append(
            DocumentRecord(
                id=document_id(spec.sdk, version, rel),
                sdk=spec.sdk,
                version=version,
                path=rel,
                url=url,
                title=page.title,
                description=page.description,
                platforms=page.platforms,
                content_hash=sha256(raw),
            )
        )
        chunks.extend(page_chunks)
    return documents, chunks, skipped


def ingest(
    sdk: str,
    version: str,
    *,
    store: Any,
    embedder: EmbeddingProvider | None,
    ref: str = "main",
    fetch_mode: FetchMode = "tarball",
    github_token: str | None = None,
    cache_root: Path | None = Path(".cache/sources"),
    batch_size: int = 100,
    batch_tokens: int | None = 20_000,
    tpm_limit: int | None = 25_000,
    pause_s: float = 1.0,
    dry_run: bool = False,
    limit: int | None = None,
    max_embed: int | None = None,
    files: dict[str, str] | None = None,
    commit_sha: str | None = None,
    client: httpx.Client | None = None,
    progress: Callable[[str], None] = lambda message: None,
) -> IngestReport:
    """Ingest one (source, version). `files`/`commit_sha` skip the download (tests)."""
    started = time.monotonic()
    validate_version(sdk, version)
    spec = SOURCES[sdk]
    if files is None:
        http = client or httpx.Client(
            timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True
        )
        try:
            commit_sha = resolve_commit(http, spec.repo, ref, github_token)
            progress(f"{spec.repo}@{ref} -> {commit_sha[:10]}; fetching ({fetch_mode})...")
            files = fetch_docs(
                spec.repo,
                commit_sha,
                spec.prefix(version),
                lambda path: spec.include(version, path),
                mode=fetch_mode,
                token=github_token,
                cache_root=cache_root,
                client=http,
            )
        finally:
            if client is None:
                http.close()
    commit_sha = commit_sha or "unknown"
    report = IngestReport(
        sdk=sdk, version=version, repo=spec.repo, commit_sha=commit_sha, fetch_mode=fetch_mode
    )
    report.files = len(files)
    if not files:
        raise RuntimeError(f"no documentation files found for {sdk}@{version}")

    documents, chunks, skipped = build_corpus(spec, version, files, limit=limit)
    report.documents, report.skipped_empty, report.chunks = len(documents), skipped, len(chunks)
    report.chunks_by_kind = dict(Counter(c.kind for c in chunks))
    report.tokens = sum(c.tokens for c in chunks)
    report.avg_tokens = report.tokens / len(chunks) if chunks else 0.0
    report.oversized_chunks = sum(1 for c in chunks if c.tokens > MAX_TOKENS)
    progress(f"parsed {len(documents)} pages into {len(chunks)} chunks ({report.tokens} tokens)")

    counter = default_counter()
    if embedder is not None:
        report.embedding_model, report.dimensions = embedder.model, embedder.dimensions
        price = EMBEDDING_PRICES.get(embedder.model, 0.0)
        report.embedding_usd_full_corpus = (
            sum(counter.count(c.embed_text) for c in chunks) * price / 1_000_000
        )
    if dry_run or embedder is None:
        report.dry_run = True
        report.elapsed_s = time.monotonic() - started
        return report

    before = len(embedder.ledger.records)
    embeddings, embed_report = embed_with_cache(
        embedder,
        store,
        [(c.content_hash, c.embed_text) for c in chunks],
        batch_size=batch_size,
        batch_tokens=batch_tokens,
        tpm_limit=tpm_limit,
        pause_s=pause_s,
        on_batch=lambda done, total: progress(f"  embedded {done}/{total}"),
        max_new=max_embed,
    )
    records = embedder.ledger.records[before:]
    report.embedded, report.embed_cached = embed_report.embedded, embed_report.cached
    report.embed_batches = embed_report.batches
    report.embed_missing, report.embed_stopped = embed_report.missing, embed_report.stopped
    if embed_report.stopped:
        progress(f"embedding stopped early ({embed_report.stopped}); {embed_report.missing} left")
    report.embedding_tokens = sum(r.tokens for r in records)
    report.embedding_usd = sum(r.cost_usd for r in records)

    report.elapsed_s = time.monotonic() - started
    report.db = store.sync_corpus(
        sdk=sdk,
        repo=spec.repo,
        licence=spec.licence,
        attribution_url=spec.attribution_url,
        version=version,
        commit_sha=commit_sha,
        embedding_model=embedder.model,
        dimensions=embedder.dimensions,
        documents=documents,
        chunks=chunks,
        embeddings=embeddings,
        stats={k: v for k, v in report.as_dict().items() if k != "db"},
    )
    report.elapsed_s = time.monotonic() - started
    return report
