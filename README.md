# DocPilot RN

**Ask an Expo or React Native question for the version you are on; get a streamed answer
whose citations were checked before you saw them.** DocPilot indexes the Expo SDK 58 and 57
docs, the unversioned Expo guides and the React Native docs, retrieves with pgvector and
Postgres full-text fused by reciprocal rank fusion, answers with Groq `gpt-oss-120b`
(Gemini fallback), and verifies every `[n]` against the passages it actually retrieved. A
"What changed?" mode answers the same question for two SDK versions as a structured diff.

Level 2 project of the [AI Engineering Journey](https://github.com/saad-official/ai-engineering-journey)
(Phase 2: embeddings, retrieval, RAG) and app 8 of the Vibe Build Series. Spec:
[docs/spec.md](docs/spec.md).

## How it works

```
ingest:  GitHub @ commit → MDX → Markdown → heading-bounded chunks (400-700 tok, code/tables
         whole) → embeddings (cached by content hash) → Neon: vector + tsvector(english, simple)
query:   question → vector top-40 ∪ full-text top-40 (version filter) → RRF k=60 + API boost
         → (rerank) → [1]..[8] in tagged passages → streamed answer → citation verifier → SSE
```

- **Version-aware**: Expo questions search the chosen SDK version plus the unversioned
  guides; every passage and citation carries its version.
- **Verified citations**: unknown `[n]` and quotes that are not in the cited passage are
  removed; an answer with no surviving citation is labelled unsupported.
- **Measured**: a 40-question golden set (4 version-sensitive pairs, 4 unanswerable) scores
  four retrieval configurations, citation precision, refusals, latency and cost.

Details: [architecture](docs/architecture.md) · [API](docs/api.md) · [setup](docs/setup.md) ·
[evals](docs/evals.md) · [costs](docs/costs.md) · decisions:
[embedding provider](docs/decisions/0001-embedding-provider.md),
[chunking](docs/decisions/0002-chunking.md),
[hybrid and rerank](docs/decisions/0003-hybrid-and-rerank.md),
[citation verification](docs/decisions/0004-citation-verification.md)

## Quick start

```powershell
uv sync
Copy-Item .env.example .env        # DATABASE_URL(+_DIRECT_URL), GEMINI_API_KEY, GROQ_API_KEY
uv run migrate
uv run ingest react-native --version current --fetch tree
uv run ingest expo --version v58.0.0 --fetch tree
uv run uvicorn docpilot.api.main:app --port 7861      # OpenAPI at /api/docs
uv run python scripts/smoke_live.py "How do I keep the splash screen visible?" v58.0.0
```

## Development

```powershell
uv run ruff check . ; uv run ruff format --check . ; uv run pytest -q
uv run evals --recorded            # golden set from the recorded fixture: no database, no keys
uv run evals --config hybrid       # live: four retrieval configs, writes docs/evals.md
```

No test touches the network: providers are faked or mocked with `respx`, Postgres is an
in-memory store (the `postgres`-marked tests run against pgvector in CI).

## Stack

Python 3.12 · FastAPI (SSE) · Pydantic · [llm-kit](https://github.com/saad-official/ai-engineering-journey/tree/main/packages/llm-kit)
(provider layer with cost ledger) · Groq `gpt-oss-120b` / `gpt-oss-20b` and Gemini
`gemini-3.5-flash-lite` · Gemini `gemini-embedding-001` (768-d) or Voyage `voyage-4-lite` +
`rerank-2.5-lite` · Neon Postgres + pgvector (HNSW) + `tsvector` · psycopg 3 · tiktoken ·
Next.js UI in `web/` · Vercel (API and web) · GitHub Actions (CI, ingestion)

## Sources and licences

Expo documentation: [expo/expo](https://github.com/expo/expo) (MIT). React Native
documentation: [react/react-native-website](https://github.com/react/react-native-website)
(CC BY 4.0), attributed on every citation by its URL. DocPilot is not affiliated with Expo
or Meta.

## Learning: explain it back

Questions to answer without looking, with model answers.

**1. Why hybrid retrieval instead of vectors alone?**
Embeddings capture meaning ("keep the splash screen up" finds "delay hiding the splash
screen") but blur exact identifiers: `useLocalSearchParams` and `useGlobalSearchParams` are
neighbours in vector space and opposites for the developer asking. Full-text search is the
reverse: exact on tokens, blind to paraphrase. Docs questions mix both, so each retriever
covers the other's failure mode, and the `simple` (unstemmed) tsvector plus the API-name
boost make exact API names win when the question names one. The eval table shows each
retriever alone against the fusion.

**2. Why reciprocal rank fusion instead of adding the scores?**
Cosine similarity (0.6-0.8 for anything on topic) and `ts_rank` (small, length-dependent)
live on unrelated scales, so any weighted sum needs calibrating per corpus and breaks when
either distribution moves. RRF uses ranks only: `Σ 1/(60 + rank)`. The constant 60 makes
agreement matter more than a single first place: a chunk third in both lists (0.0317) beats
one first in a single list (0.0164). One parameter, no training data, robust.

**3. Why rerank, and why only the top 40?**
A bi-encoder embeds the question and each passage separately, so fine distinctions (this
version, this platform, this exact option) are compressed away. A cross-encoder reranker
reads question and passage together and scores the pair, which is much more accurate and
much too slow to run over 5,000 chunks. Running it over the 40 fused candidates gets its
accuracy at the cost of one API call; without a key the RRF order is used, and the eval
measures what that costs.

**4. Why verify citations in code when the prompt already says "cite only passages"?**
A prompt is a request; a check is a guarantee. The set of valid citations is known exactly
(the passages in the prompt), and whether a quoted sentence appears in a passage is a
string search. Both are free, deterministic and testable, while a second "check your
citations" model call costs as much as the answer and can be wrong the same way. What code
cannot check (is a paraphrase supported?) is measured by the LLM judge on the golden set.

**5. Why exactly one embedding model per corpus?**
A vector only means something relative to other vectors from the same model: two models
map the same text to unrelated coordinates, and different dimensions cannot even be
compared. A query embedded with model B against documents from model A returns a ranked
list that looks fine and is noise; nothing errors. So each corpus records its model and
dimension, ingestion refuses to mix, the retriever refuses to search a corpus with another
model, and switching models is an explicit re-embed (docs/setup.md).

## Live

- Web: https://docpilotrn.vercel.app · API: https://docpilot-rn-api.vercel.app (`/api/docs`)
- Corpus live on 5 Oct 2026: Expo SDK 58 (877 chunks), SDK 57 (833), unversioned guides (2,432) and React Native current (889), all full-text searchable; vectors fill in at Gemini's free limit of 1,000 embeddings a day (a Voyage key removes the wait).
- Verified against production: "How do I schedule a local notification with expo-notifications?" for SDK 58 streamed an answer in 2.0 s on Groq `gpt-oss-120b`, with one verified citation to the SDK 58 Notifications page and nothing removed, for $0.00047 at paid rates.
- Measured eval (40 questions, full-text configuration): recall@5 0.86, MRR 0.69, citation precision 0.99, 29 of 35 answerable questions answered and all 4 unanswerable ones refused. Vector, hybrid and rerank rows follow once the corpus is fully embedded.
