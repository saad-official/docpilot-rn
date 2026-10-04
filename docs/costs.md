# Costs

Every number is at **paid** rates, even though everything ran on free tiers and cost
$0.00: the question is what real traffic would cost. Generation costs come from llm-kit's
`Ledger` (provider-reported tokens, prices from `llm_kit.pricing`, verified 2026-09-05);
embedding and rerank costs from the project's `EmbeddingLedger` (`embeddings.py`,
prices checked 2026-10-04). Gemini's batch embedding endpoint reports no token counts, so
embedding tokens are counted locally with `o200k_base` and labelled as estimates.

Prices (USD per 1M tokens): `gemini-embedding-001` 0.15 · `voyage-4-lite` 0.02 ·
`rerank-2.5-lite` 0.02 · `openai/gpt-oss-120b` 0.15 in / 0.60 out · `openai/gpt-oss-20b`
0.075 / 0.30 · `gemini-3.5-flash-lite` 0.30 / 2.50.

## Ingestion (one-off, 2026-10-05)

| Corpus | Chunks | Tokens embedded (title + heading path + content) | Gemini at paid rates | Voyage at paid rates |
|---|---|---|---|---|
| Expo v58.0.0 | 877 | 286k | $0.0429 | $0.0057 |
| Expo v57.0.0 | 833 | 268k | $0.0402 | $0.0054 |
| Expo unversioned guides | 2,432 | 851k | $0.1277 | $0.0170 |
| React Native current | 889 | 350k | $0.0525 | $0.0070 |
| **Total** | **5,031** | **1.76M** | **$0.263** | **$0.035** |

The spec estimated ~600k tokens; the real corpus is ~3x that, mostly the unversioned guides
(EAS, Router, tutorials) and the heading context added to every chunk. Re-ingesting
unchanged docs costs $0 (content-hash cache); a typical SDK point release changes a few
dozen chunks, i.e. fractions of a cent.

**The free tier is the constraint, not the price**: Gemini embeds at most 1,000 texts per
day per project (measured; decision 0001), so the first full embedding takes five days on
the free tier. As of this run 532 of 5,031 chunks have vectors; the daily GitHub Actions job
(`ingest.yml`) adds ~900 a day. A paid key ($0.26 once) or Voyage ($0.035 once; 200M free
tokens) removes the wait.

## Per question (measured, golden set, full-text retrieval, 39 answered questions)

| Served by | Answers | Mean prompt / completion tokens | Mean cost | Median latency |
|---|---|---|---|---|
| Groq `gpt-oss-120b` | 9 | 3,212 / 258 | $0.00064 | 5.6 s |
| Gemini `gemini-3.5-flash-lite` (fallback) | 30 | 3,036 / 123 | $0.00122 | 6.5 s |
| **All** | 39 | | **$0.00109** | 6.4 s |

Query embedding adds ~$0.000002 per question (one ~15-token call), rerank would add
~$0.0003 (40 passages x ~400 tokens at $0.02/1M). The whole 40-question eval run cost
$0.042 at paid rates.

What the numbers say:

- **A question costs about a tenth of a cent** on the primary route, well inside the
  $0.02 per-question ceiling enforced by the ledger before every call.
- **The fallback doubles the price**: Gemini flash-lite's output tokens cost 4x
  gpt-oss-120b's. In the eval it served 77% of answers because questions arrived back to
  back and Groq's 8,000 tokens-per-minute free limit fills after one ~6k-token question; the
  router takes the fallback instead of making the user wait (decision recorded in
  `llm.py`). At interactive rates most answers stay on Groq.
- **Prompts are smaller than budgeted**: ~3.1k prompt tokens on average against the
  6,000-token passage budget, because the top 8 chunks average ~350 tokens. The budget
  matters for the occasional oversized code chunk.
- **Diff mode** costs one structured call over ~3-6k tokens (measured: 3,077 in / 376 out,
  $0.00069 on Groq) plus two query embeddings; the prose is rendered by code, not by a
  second call.

Not measured yet: rerank (no Voyage key), the LLM judge (implemented, not run).
