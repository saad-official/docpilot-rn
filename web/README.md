# DocPilot RN: web

Next.js 16 (App Router) front end for the DocPilot RN API. Deployed to Vercel with this folder as the project root.

## Run locally

```bash
pnpm install
cp .env.example .env.local        # NEXT_PUBLIC_API_URL defaults to http://localhost:7860
pnpm dev
```

Without the API, run on fixtures: set `NEXT_PUBLIC_API_MOCK=1` and restart `pnpm dev`. Mock mode serves an Expo SDK 58
answer (local notifications, 5 passages, 3 cited, one invented `[7]` removed by the verifier) and a real SDK 52 → 53 diff
(`shouldShowAlert` deprecated) from `lib/mock.ts`. On `/ask`, a question containing `rate limit`, `offline`, `fail`,
`cut off` or `weather` shows the 429, network error, mid-stream error, cut-off stream and unsupported-answer states.
`/q/demo-notifications` and `/q/demo-diff` are stored answers.

## Checks

```bash
pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm lint && pnpm test
NEXT_PUBLIC_API_URL=http://localhost:7860 pnpm build
```

## Layout

- `app/` pages: `/` landing, `/ask` the tool, `/q/[id]` stored answer (server-rendered, noindex), `/docs`,
  `api/health` (proxies the API health check).
- `lib/api.ts` the API contract (zod, tolerant of missing fields) and `streamAsk` (POST + SSE over fetch),
  `lib/sse.ts` the event-stream parser, `lib/turn.ts` stream events folded into an answer and the thread,
  `lib/markdown.ts` a small answer renderer with citation markers, `lib/highlight.ts` quote highlighting,
  `lib/mock.ts` fixtures, `lib/evals-sample.ts` the landing-page eval table (copy from `docs/evals.md`).
- `components/answer/` the answer document, citation chips, source panel and diff table (server-safe, shared by all pages).
- `components/ask/` the client workspace, feedback and share controls.
