"""`uv run ingest <expo|react-native> --version <v>`: build or refresh one corpus.

Examples:
    uv run ingest expo --version v58.0.0
    uv run ingest expo --version unversioned --fetch tree
    uv run ingest react-native --version current
    uv run ingest expo --version v58.0.0 --dry-run        # parse + chunk only, no keys needed

Exit codes: 2 bad arguments or missing configuration, 3 download failed, 4 embedding failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from ..config import get_settings
from ..embeddings import EmbeddingError, make_embedder
from .fetch import FetchError

app = typer.Typer(add_completion=False, help=__doc__)


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


@app.command()
def run(
    source: Annotated[str, typer.Argument(help="expo or react-native")],
    version: Annotated[
        str, typer.Option("--version", "-v", help="v58.0.0, unversioned, or current (RN)")
    ],
    ref: Annotated[str, typer.Option(help="Branch, tag or SHA to pin (default: main)")] = "main",
    fetch: Annotated[
        str, typer.Option(help="tarball (spec; fast links) or tree (Trees API + raw files)")
    ] = "tarball",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Parse and chunk only")] = False,
    limit: Annotated[int | None, typer.Option(help="Only the first N pages (debugging)")] = None,
    max_embed: Annotated[
        int | None,
        typer.Option(help="Embed at most N new chunks this run (spread a free daily quota)"),
    ] = None,
    report_json: Annotated[
        Path | None, typer.Option("--report", help="Also write the report as JSON")
    ] = None,
) -> None:
    settings = get_settings()
    if source not in ("expo", "react-native"):
        _err("source must be 'expo' or 'react-native'")
        raise typer.Exit(2)
    if fetch not in ("tarball", "tree"):
        _err("--fetch must be 'tarball' or 'tree'")
        raise typer.Exit(2)

    from .pipeline import ingest

    store = None
    embedder = None
    if not dry_run:
        dsn = settings.dsn(direct=True)
        if not dsn:
            _err("DATABASE_URL (or DATABASE_DIRECT_URL) is not set; use --dry-run to parse only")
            raise typer.Exit(2)
        try:
            embedder = make_embedder(settings)
        except ValueError as exc:
            _err(str(exc))
            raise typer.Exit(2) from exc
        from ..db.postgres import PostgresStore

        store = PostgresStore(dsn)
    token = settings.github_token.get_secret_value() if settings.github_token else None
    try:
        report = ingest(
            source,
            version,
            store=store,
            embedder=embedder,
            ref=ref,
            fetch_mode=fetch,  # type: ignore[arg-type]
            github_token=token,
            batch_size=settings.embed_batch_size,
            batch_tokens=settings.embed_batch_tokens,
            tpm_limit=settings.embed_tpm or None,
            pause_s=settings.embed_pause_s,
            dry_run=dry_run,
            limit=limit,
            max_embed=max_embed,
            progress=_err,
        )
    except ValueError as exc:
        _err(str(exc))
        raise typer.Exit(2) from exc
    except FetchError as exc:
        _err(f"download failed: {exc}")
        raise typer.Exit(3) from exc
    except EmbeddingError as exc:
        _err(f"embedding failed (re-run to resume from the cache): {exc}")
        raise typer.Exit(4) from exc
    finally:
        if store is not None:
            store.close()
    print(report.summary())
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
