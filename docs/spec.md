# DocPilot RN — product and technical spec

Status: approved 2026-10-04. Level 2 project of the [AI Engineering Journey](https://github.com/saad-official/ai-engineering-journey) (Phase 2: embeddings, retrieval, RAG), app 8 of the Vibe Build Series. The 12-question evaluation lives in the journey's `PROJECTS.md`; this file is the build contract.

## 1. Problem

Expo and React Native documentation changes every SDK release. Answers found online target other versions, so developers lose hours to version drift: an API that moved, a config key that was renamed, a plugin that became built in. Search returns pages; developers want an answer for the version they are actually on, with the source to prove it.

## 2. Users

React Native and Expo developers (the author's own community), later any team with versioned SDK docs.

## 3. What it does (MVP)

Ask a question, pick the Expo SDK version you are on, get a streamed, grounded answer with numbered citations that link to the exact docs page and heading. Every citation is verified against the retrieved chunks before it is shown; an answer with no supporting passages says so instead of guessing. A **"What changed?"** mode answers the same question for two versions and explains the difference with citations to both.

Corpus for the demo: two Expo SDK versions (the latest two under `docs/pages/versions/`) plus the unversioned guides (`docs/pages/guides`, `eas`, `router`, and so on, excluding `ja/`), from the MIT-licensed `expo/expo` repository; React Native docs (CC-BY 4.0, `facebook/react-native-website/docs`) as a second source with attribution, current version only.

Not in MVP: accounts, uploading your own docs, more SDKs, multi-turn memory beyond the current thread (the thread lives in the browser), feedback loop into evals (buttons are recorded, not acted on).

## 4. Architecture

```
ingest (CLI, offline)                              query (FastAPI, Vercel Python)
GitHub tarball -> parse MD/MDX -> structure-aware   question + version -> rewrite (optional, cheap)
chunks {sdk, version, path, heading_path, url,      -> hybrid retrieval: pgvector cosine top-40 ∪ Postgres
anchor, kind: prose|code|table, tokens}             full-text top-40 (version filter) -> RRF -> rerank
-> embed (Voyage voyage-4-lite 1024-d or Gemini     top-8 (Voyage rerank-2.5-lite; fallback: no rerank)
gemini-embedding-001 768-d; one, configured)        -> context with [n] ids -> streamed answer (Groq
-> upsert by content hash into Neon                 gpt-oss-120b, fallback Gemini) -> citation verifier
                                                    -> SSE to UI; log retrieval + answer + usage
```

- **Parsing**: MDX frontmatter (`title`, `description`, `platforms`), headings as the chunk boundary, code blocks never split (a code block longer than the budget becomes its own chunk with its heading context), tables kept whole, Expo-specific components (`<APISection>`, `<Terminal>`, `<Tabs>`) reduced to their text and commands. Each chunk records `heading_path` ("Guides › Push notifications › Setup") and a URL with anchor (`https://docs.expo.dev/versions/v58.0.0/sdk/notifications/#setup`).
- **Chunking**: target 400–700 tokens prose, overlap 1 heading sentence, `o200k_base` counting. Measured in `docs/evals.md`: chunk size vs recall@5.
- **Embeddings**: provider abstraction with two implementations (Voyage, Gemini) chosen by env; dimension stored with the corpus; a corpus is tied to one embedding model (re-embed to switch). Batched, cached by content hash, idempotent re-ingest.
- **Hybrid retrieval**: pgvector HNSW (cosine) with a `WHERE sdk = $1 AND version IN ($2, 'unversioned')` filter, plus Postgres `tsvector` (english, with API names kept as exact tokens via a simple dictionary) on `content` and `heading_path`; reciprocal rank fusion (k=60); optional rerank of the top 40 to top 8 with Voyage `rerank-2.5-lite`; without a reranker, RRF order is used. Exact API-name matches (`expo-notifications`, `useRouter`) get a boost.
- **Generation**: system prompt demands grounding ("use only the passages; cite as [n]; if the passages do not answer, say what is missing and which page to read"), temperature 0.2, streamed. Doc text is wrapped in tags and the model is told to ignore instructions inside it.
- **Citation verifier** (deterministic): every `[n]` must map to a retrieved chunk; quoted fragments are checked against the chunk text (normalised); unverifiable citations are removed from the rendered answer and counted; answers citing nothing are labelled "unsupported".
- **"What changed?"**: run retrieval for both versions, give the model both passage sets with version tags, ask for a structured diff (`DiffAnswer { summary, changes: [{ kind: added|removed|renamed|behaviour, before, after, citations }] }`) then prose.

## 5. Data model (Neon, schema `docpilot`)

```
sources(id, name: expo|react-native, repo, licence, attribution_url)
corpora(id, source_id, version, commit_sha, embedding_model, dimensions, chunk_count, ingested_at)
documents(id, corpus_id, path, url, title, description, platforms text[], content_hash)
chunks(id, document_id, corpus_id, version, heading_path, anchor, url, kind, content, tokens,
       content_hash, embedding vector(DIM), tsv tsvector generated)
       indexes: hnsw (embedding vector_cosine_ops), gin (tsv), (corpus_id, version)
questions(id, created_at, version, mode: answer|diff, question, rewritten, retrieval jsonb (ids, scores, fused, reranked),
          answer, citations jsonb, verification jsonb, usage jsonb, latency_ms, feedback: up|down|null)
eval_runs(id, golden_version, config jsonb, metrics jsonb, created_at)
```

## 6. API (FastAPI, `/api`)

- `GET /api/versions` → sources, versions available, chunk counts, embedding model.
- `POST /api/ask` `{ question, sdk: "expo"|"react-native", version, mode: "answer"|"diff", compare_version?, thread?: [{role, content}] (last 4 turns, used only for query rewriting) }` → SSE stream of events: `retrieval` (chunks with ids, titles, urls, scores), `token` (text deltas), `citations` (verified list), `done` (usage, latency, question id), `error`. Rate limit: 30 questions per hour per IP.
- `POST /api/questions/{id}/feedback` `{ feedback: "up"|"down" }`.
- `GET /api/questions/{id}` → stored record (for shareable links `/q/[id]` in the UI).
- `GET /api/health` → db, corpus freshness, providers.
- Ingestion is a CLI (`uv run ingest expo --version v58.0.0`), run locally or from a GitHub Actions workflow with the database URL as a secret; never from the web.

## 7. Evaluation (`evals/`)

Golden set of 40 questions across the two Expo versions (30) and React Native (10), each with expected source URLs (page + anchor where it matters) and a short reference answer; 8 of them are version-sensitive (the answer differs by version), 4 are unanswerable from the docs (must refuse). Metrics computed by code: recall@5 and MRR of expected URLs across retrieval configurations (vector only, full-text only, hybrid, hybrid+rerank), citation precision (verified / emitted), refusal correctness, latency p50/p95, cost per question at paid rates. LLM-judge (rubric 1–5) for faithfulness and completeness, reported separately. `uv run evals --config hybrid_rerank` writes `docs/evals.md` with a results table; the retrieval metrics run in CI against the live Neon corpus (read-only) when `DATABASE_URL` is available, otherwise against a recorded fixture.

## 8. Costs (`docs/costs.md`)

Embedding ~750 files (~2 MB text, ~600k tokens) once: free on both Voyage (200M free tokens) and Gemini. Per question: embedding of the query, one rerank call, one generation (≈3–5k input tokens, ≤600 output): a fraction of a cent at paid rates; measured by the ledger and published.

## 9. Hosting (free)

API on Vercel Python runtime (see Changelog Forge decision 0002; same pattern: root `main.py`, `vercel.json` framework `fastapi`); streaming SSE within one request (< 60 s). Web on Vercel (root `web/`). Neon Free project `docpilot-rn` with pgvector. Ingestion via GitHub Actions `workflow_dispatch` (free on public repos) or locally. Langfuse Hobby optional.

## 10. Identity

Reference-manual calm with a terminal edge: **IBM Plex Sans** (body), **IBM Plex Serif** (headings, as in printed manuals), **IBM Plex Mono** (code, versions). Palette: graphite text on warm white, **Expo-adjacent indigo** for citations and links, **version teal** for the selected version chip, **diff amber/green** for removed/added in "What changed?". Citations render as numbered chips inline and as a right-hand source panel with the quoted passage highlighted; a version badge is always visible on every answer. Dark mode via tokens.

## 11. Learning artefacts

Concept notes to draft or update in the journey: embeddings, similarity-search, chunking-strategies, vector-databases-and-pgvector, hybrid-search-and-rrf, reranking, rag-pipeline, rag-evaluation, citations-and-grounding, query-transformations, when-not-to-use-rag. Decisions: `0001-embedding-provider.md`, `0002-chunking.md`, `0003-hybrid-and-rerank.md`, `0004-citation-verification.md`. `docs/architecture.md`, `docs/evals.md` with the configuration comparison table (the memorable artefact), `docs/costs.md`, README "explain it back" questions (why hybrid, why RRF, why rerank, why verify citations, why one embedding model per corpus).

## 12. Tests

Parser (frontmatter, headings, code blocks intact, MDX component reduction), chunker (budgets, code blocks never split, heading paths), embedding cache (content hash, batching), hybrid retrieval SQL (against PGlite? no: use a Postgres test container only when available; otherwise unit-test the SQL builder and RRF/boost math), citation verifier (mapping, quote checks, removal), diff schema validation, API streaming (fake retriever and fake LLM), eval scorers on fixtures.
