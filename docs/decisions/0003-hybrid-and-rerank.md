# 0003 — Hybrid retrieval with reciprocal rank fusion, an exact-API boost, optional rerank

Date: 2026-10-05. Status: accepted.

## Context

Developer questions mix two kinds of signal. "How do I keep the splash screen up while
loading?" is semantic: the page says "delay hiding", not "keep up". "What does
`useLocalSearchParams` return?" is lexical: the exact token is the whole question, and an
embedding model happily returns the page for `useGlobalSearchParams` instead. Neither
retriever alone handles both.

## Decision (`src/docpilot/retrieval/`)

1. **Two retrievers, top 40 each**, filtered to `sdk` and `version IN ($v, 'unversioned')`
   (Expo) or `'current'` (React Native):
   - pgvector cosine through an HNSW index; `hnsw.ef_search = 100` and pgvector 0.8's
     iterative scan are set per transaction so the version filter cannot starve the top 40;
   - Postgres full-text on two generated `tsvector` columns: `english` (stemming,
     stop words; heading text weight A, content B) and `simple` (exact tokens such as
     `expo-notifications`, `useRouter`, `app.json`). Question terms are OR-ed
     (`websearch_to_tsquery` ANDs them, and almost no page contains every word of a
     question); `ts_rank` with log-length normalisation; exact-token matches count double.
2. **Reciprocal rank fusion**, k = 60: `score = Σ 1/(60 + rank)`. Ranks, not scores:
   cosine and `ts_rank` are on unrelated scales, and any weighted sum needs re-tuning per
   corpus. k = 60 rewards agreement: first in one list (0.0164) loses to third in both
   (0.0317).
3. **Exact-API boost** on the RRF scale: a chunk whose title or heading path contains an
   API name from the question (`expo-*`, `use[A-Z]…`, `…Screen`, camelCase, `@scope/pkg`,
   `*.json`) gets +0.02, a body match +0.008, capped at +0.03. Enough to lift a section
   *about* the API past single-list rankings, not past a chunk both retrievers agree on.
4. **Rerank** (`hybrid_rerank`, served by default): Voyage `rerank-2.5-lite` re-orders the
   fused top 40 to 8 when `VOYAGE_API_KEY` is set; without it the RRF order is used and the
   retrieval event reports `config: "hybrid"`.
5. **Context**: top 8, numbered [1]..[8], each in a `<passage>` tag with version, title,
   section and URL, under a ~6,000-token budget (Groq's free tier allows 8,000 tokens per
   minute per model; passages + prompt + answer must fit one minute).

## Evidence

`docs/evals.md` has the four-way comparison on the golden set. One measured tuning
decision so far: full-text ranking with `ts_rank_cd(.., 32)` scored recall@5 0.72 / MRR
0.51 on the 36 answerable questions; `ts_rank(.., 1)` scored 0.86 / 0.69 (chosen on the
golden set, so optimistic).

## Alternatives

- Weighted score blending (`0.7 * cosine + 0.3 * bm25`): needs calibration, breaks when
  either distribution shifts. RRF has one parameter that the literature leaves at 60.
- Vector only with a bigger model: still misses exact identifiers; costs more per query.
- A dedicated search engine (Elastic, Typesense): a second datastore for 5,000 chunks.
  Postgres already holds the vectors; `tsvector` + GIN is enough at this size.
