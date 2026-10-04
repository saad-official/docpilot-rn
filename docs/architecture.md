# Architecture

DocPilot RN answers Expo and React Native questions for the version you are on, with
citations that are checked before they are shown. Two halves that share only a database:

```
INGEST (CLI / GitHub Actions, offline)                QUERY (FastAPI on Vercel, per question)

GitHub @ pinned commit                                 POST /api/ask {question, sdk, version}
  │ tarball (stream) or Trees API + raw files            │ rate limit (bucket + Postgres count)
  ▼                                                      ▼ store question (pending)
MDX ─reduce─▶ Markdown ─parse─▶ sections (heading_path,  (rewrite follow-up, cheap tier)
  anchor) ─chunk─▶ 400-700 tok, code/tables atomic       │
  │                                                      ├─▶ embed query ─▶ pgvector top-40 ─┐
  ▼ content hash                                         └─▶ websearch tsquery top-40 ───────┤
embedding cache (hash, model) ◀─▶ Gemini / Voyage        RRF k=60 + exact-API boost ◀────────┘
  │                                                      (Voyage rerank top-40 → 8)
  ▼ one transaction per corpus                           context [1]..[8], ≤ 6k tokens
Neon Postgres (schema docpilot)  ─────────────────────▶  stream answer (Groq gpt-oss-120b,
  sources · corpora · documents · chunks(vector,           Gemini fallback) ── SSE token events
  tsv english, tsv simple) · embedding_cache ·           verify citations ── SSE citations
  questions · eval_runs                                  store question (done) ── SSE done
```

## Code map (`src/docpilot/`)

| Module | Responsibility |
|---|---|
| `ingest/sources.py` | What to fetch per source/version; path → public URL |
| `ingest/fetch.py` | Pinned-commit download: streamed tarball or Trees API + raw files; local cache |
| `ingest/mdx.py` | MDX → Markdown (component policy, imports, partials, annotations) |
| `ingest/parse.py` | Frontmatter, sections, heading paths, anchors, blocks |
| `ingest/chunker.py` | Budgets, atomic blocks, heading-sentence overlap, merge, ids |
| `ingest/pipeline.py`, `cli.py` | `uv run ingest …`: orchestrate, report counts and cost |
| `embeddings.py` | `EmbeddingProvider` (Gemini, Voyage), ledger, cache, token-aware batching and pacing |
| `retrieval/query.py`, `sql.py` | Question → full-text queries and API names; SQL builders |
| `retrieval/search.py`, `fusion.py`, `rerank.py`, `context.py` | Four retrieval configs, RRF, boost, rerank, passages |
| `llm.py`, `routing.toml` | Adapter over llm-kit: fallback routes, cooldowns, TPM pacing, streaming fallback |
| `answer/service.py` | One question as an event stream (answer and diff modes) |
| `answer/verify.py`, `diff.py` | Citation verifier; structured diff schema and rendering |
| `api/` | FastAPI routes, schemas, rate limiting |
| `db/` | `Store` protocol, Postgres and in-memory stores, migrations |
| `evals/` | Golden set runner, scorers, judge |
| `prompts/*.v1.md` | Versioned prompts (id `name.v1@sha8` stored with each answer) |

## Decisions

[0001 embedding provider](decisions/0001-embedding-provider.md) ·
[0002 chunking](decisions/0002-chunking.md) ·
[0003 hybrid and rerank](decisions/0003-hybrid-and-rerank.md) ·
[0004 citation verification](decisions/0004-citation-verification.md) ·
hosting follows Changelog Forge's
[0002-hosting](https://github.com/saad-official/changelog-forge/blob/main/docs/decisions/0002-hosting.md)
(root `main.py`, `vercel.json` `framework: fastapi`, SSE within one request).

## Choices the spec left open

- **Fetch transport.** The spec says tarball; it is the default and what the GitHub Action
  uses. On the development machine the react-native-website tarball (150 MB) took 10.6 min
  at 236 KB/s, so `--fetch tree` (Trees API for the docs subtree, then each file from
  `raw.githubusercontent.com` at the same commit) fetches only the ~10 MB of docs. Both pin
  every file to the recorded `commit_sha`.
- **Expo unversioned scope**: everything under `docs/pages/` except `versions/`, `ja/`,
  `internal/` and `archive/` (archived pages describe removed workflows and would win
  queries they should not). `versions/unversioned/` (next SDK, unreleased) is excluded.
- **React Native "current"** is `docs/` of `react/react-native-website` (the repository
  moved from `facebook/`); `docs/` is the next release, which the site serves at
  `/docs/next/`; citations link to `/docs/<id>` (the latest release), which differs only
  for pages changed since the last release.
- **Partial embedding is a first-class state.** Chunks are stored and full-text searchable
  before they have vectors; vectors are added as the embedding quota allows (0001).
- **Diff mode** compares the versioned reference only (the unversioned guides are the same
  on both sides), numbers the older version's passages first, and renders prose from the
  structured diff by code instead of a second generation call (fits the 8K TPM free tier).
- **Rate limit** counts every question (both modes) per salted IP hash.
- **Query rewrite** only runs with a `thread`; the rewritten query drives retrieval, the
  original question is what the model answers.
- **Questions are stored before the first event** (status `pending`), so a dropped stream
  is recoverable from `GET /api/questions/{id}`, and failures are recorded.
- **Events carry `kind`** in the JSON (unnamed SSE messages with `id:` lines, as in
  Changelog Forge), plus a `diff` event the spec did not list, consumed by the web app.

## What changes in production

- Neon and Vercel in the same region: measured locally, every Neon round trip costs ~0.5 s
  from the development machine, which dominates the retrieval latencies in `docs/evals.md`
  (the full-text query itself executes in ~30 ms).
- Voyage instead of free-tier Gemini (no daily wall; reranker; cheaper).
- The TypeDoc API JSON ingested alongside the MDX (0002, open).
