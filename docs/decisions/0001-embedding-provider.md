# 0001 — Embedding provider: Gemini `gemini-embedding-001` at 768 dimensions, Voyage as the switch

Date: 2026-10-05. Status: accepted, with a measured constraint (see "What the first run taught").

## Context

The corpus is ~5,000 chunks (~1.7M tokens: Expo SDK 58 and 57, the unversioned Expo
guides, React Native) and every question embeds its query. The spec (section 4) allows two
providers behind one abstraction, chosen by environment, with one model per corpus.

| | Gemini `gemini-embedding-001` | Voyage `voyage-4-lite` |
|---|---|---|
| Key available today | yes (journey `.env`) | no |
| Paid price | $0.15 / 1M tokens | $0.02 / 1M tokens (200M free tokens per account) |
| Dimensions | 3072, Matryoshka-truncatable (768 used) | 1024 (256-2048 selectable) |
| Query vs document | `taskType` RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT | `input_type` query / document |
| Free-tier limits (measured) | **100 texts/minute, 1,000 texts/day per model**, each text in a batch counting as one request | 3 RPM / 10K TPM without a payment method |
| Rerank from the same vendor | no | `rerank-2.5-lite` |

## Decision

- `EmbeddingProvider` protocol with `GeminiEmbeddings` and `VoyageEmbeddings`
  (`src/docpilot/embeddings.py`), selected by `EMBEDDING_PROVIDER=auto|gemini|voyage`
  (auto = Voyage when its key exists). Two small HTTP clients rather than llm-kit: llm-kit
  speaks the OpenAI chat format, and neither `taskType` nor Voyage fit through it.
- Gemini at **768 dimensions** (`outputDimensionality`), L2-normalised (Google's guidance:
  truncated Matryoshka vectors must be re-normalised for cosine). 768 keeps the HNSW index
  and Neon storage small (~3 KB per vector) at a small quality cost versus 3072.
- **One model per corpus.** `corpora.embedding_model` and `dimensions` record what built a
  corpus. `PostgresStore.sync_corpus` refuses to add vectors from another model, and the
  retriever refuses to search a corpus with a model other than the one embedding the query
  (`embedding_model_mismatch`). Vectors from different models live in unrelated spaces: a
  mixed search returns confident nonsense, not an error.
- The vector column is typed (`vector(768)`, from `EMBEDDING_DIMENSIONS` at migration time)
  because HNSW needs a fixed dimension. The embedding cache is untyped `vector`, keyed by
  (content hash, model, dimensions), so it can hold several models side by side.

## What the first run taught (2026-10-05)

The first live ingestion hit Gemini's free-tier quota twice, and the error bodies say
exactly which one:

1. `EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier`, limit 100: a
   100-text `batchEmbedContents` call is 100 requests, not one. Batches are now bounded by
   text count *and* estimated tokens (20k) and paced to 25k tokens per sliding minute.
2. `EmbedContentRequestsPerDayPerProjectPerModel-FreeTier`, limit **1,000**: the whole
   corpus (5,031 chunks) needs five days of free quota. The Batch API
   (`asyncBatchEmbedContent`, half price, separate limits) returns `FAILED_PRECONDITION`
   without billing.

So ingestion became **resumable by design**: chunks are always stored (full-text search
covers them at once), vectors are added as quota allows (`--max-embed`, the daily
`ingest.yml` schedule), a daily-quota 429 stops the run cleanly instead of failing it, and
the next run backfills from the cache. The query path shares the same quota, so hybrid
retrieval degrades to full-text when the query cannot be embedded, and the daily job
leaves ~100 requests a day for questions.

## Consequences and the switch

- At paid rates the whole corpus costs **$0.26** to embed once with Gemini (measured token
  counts, `docs/costs.md`); ~$0.03 with Voyage. Re-ingesting unchanged docs costs nothing
  (content-hash cache).
- **Recommended for production: Voyage** (`VOYAGE_API_KEY` + `EMBEDDING_DIMENSIONS=1024`):
  cheaper, no daily wall, and it unlocks the reranker. Switching is a re-embed of every
  corpus, documented in `docs/setup.md` ("Switching the embedding model").
- A paid Gemini key removes the wall too (the same code; ~$0.26 one-off).
