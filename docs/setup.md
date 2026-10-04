# Setup

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 from `.python-version`).
- A Neon Postgres database (pgvector is available on every Neon project).
- Keys: Gemini (embeddings and the fallback model), Groq (primary model). Optional: Voyage
  (embeddings + rerank), a GitHub token, Langfuse.

## Local development

```powershell
uv sync
Copy-Item .env.example .env          # fill DATABASE_URL, DATABASE_DIRECT_URL, GEMINI_API_KEY, GROQ_API_KEY
uv run ruff check . ; uv run ruff format --check . ; uv run pytest -q
uv run evals --recorded --no-write   # golden set against the recorded fixture, no network
```

Or `bash scripts/setup-env.sh` (Git Bash) to write `.env`, push the Vercel env and migrate.

Developing llm-kit at the same time: `uv run --with-editable ../../packages/llm-kit pytest -q`.

## Database

```powershell
uv run migrate                       # uses DATABASE_DIRECT_URL if set; EMBEDDING_DIMENSIONS=768 default
```

`0001_init.sql` creates schema `docpilot`, the `vector` extension, the tables of spec
section 5, an HNSW cosine index, GIN indexes on both `tsvector` columns, the embedding
cache, `questions` and `eval_runs`.

## Ingestion

```powershell
uv run ingest expo --version v58.0.0                # tarball of expo/expo@main (pinned SHA recorded)
uv run ingest expo --version v57.0.0 --fetch tree   # Trees API + raw files: ~10 MB instead of the repo
uv run ingest expo --version unversioned --fetch tree
uv run ingest react-native --version current --fetch tree
uv run ingest expo --version v58.0.0 --dry-run      # parse + chunk only, no keys, no database
uv run ingest expo --version v58.0.0 --max-embed 400 --report runs/v58.json
```

Idempotent: re-running with unchanged docs embeds nothing (content-hash cache) and changes
nothing; changed pages replace their chunks in one transaction; removed pages disappear.
On Gemini's free tier (1,000 embedded texts per day) a run stops cleanly at the daily wall,
leaving the remaining chunks stored without vectors; the next run (after midnight Pacific)
continues. The GitHub Actions workflow `.github/workflows/ingest.yml` does this daily
(secrets: `DATABASE_URL` = the direct URL, `GEMINI_API_KEY`; optional `VOYAGE_API_KEY`).

## Switching the embedding model (re-embed)

A corpus is tied to one model. To move to Voyage (`voyage-4-lite`, 1024-d):

```sql
-- in Neon's SQL editor (or psql with the direct URL)
DROP INDEX docpilot.chunks_embedding_hnsw;
ALTER TABLE docpilot.chunks ALTER COLUMN embedding TYPE vector(1024) USING NULL;
UPDATE docpilot.corpora SET embedding_model = 'voyage-4-lite', dimensions = 1024;
CREATE INDEX chunks_embedding_hnsw ON docpilot.chunks USING hnsw (embedding vector_cosine_ops);
```

Then set `EMBEDDING_PROVIDER=voyage`, `EMBEDDING_DIMENSIONS=1024`, `VOYAGE_API_KEY`, and
re-run the four ingest commands (they backfill every chunk's vector from the new model;
the Gemini vectors stay in `embedding_cache` should you switch back). Set the same variables
on the API deployment, since queries must be embedded with the corpus's model.

## API

```powershell
uv run uvicorn docpilot.api.main:app --port 7861 --reload     # http://localhost:7861/api/docs
uv run python scripts/smoke_live.py "How do I keep the splash screen visible?" v58.0.0
uv run python scripts/smoke_live.py "What changed for clipboard?" v58.0.0 --diff v57.0.0
```

The web app (`web/`) reads `NEXT_PUBLIC_API_URL`; add its origin to `WEB_ORIGIN`.

## Deploy (Vercel)

Two projects from this repository: `docpilot-rn-api` (root directory = repository root;
`main.py` re-exports the app, `vercel.json` selects the FastAPI preset, dependencies from
`pyproject.toml`/`uv.lock`) and `docpilot-rn` (root directory `web/`).

API environment: `DATABASE_URL` (pooled, **required**), `GROQ_API_KEY`, `GEMINI_API_KEY`,
`EMBEDDING_PROVIDER` + `EMBEDDING_DIMENSIONS` (must match the corpus), `WEB_ORIGIN`
(`https://docpilotrn.vercel.app,…`), `IP_HASH_SALT`, optionally `VOYAGE_API_KEY`,
`LANGFUSE_*`. Vercel sets `VERCEL=1`, which trusts `X-Forwarded-For` for rate limiting.

```powershell
vercel deploy --prod --yes                 # API, from the repository root
(cd web; vercel deploy --prod --yes)       # web
```

No `vercel.json` cron: there is no daily job on the API side (ingestion runs in Actions).

## Evals

```powershell
uv run evals --recorded                    # fixture, no network (CI)
uv run evals --config hybrid               # live retrieval, all four configs; writes docs/evals.md
uv run evals --config all --answers        # + an answer per question per config
uv run evals --config hybrid --answers --judge --record   # + LLM judge; save the fixture
uv run evals --sdk react-native ...        # one source only
```
