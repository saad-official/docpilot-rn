/**
 * The retrieval comparison table shown on the landing page (spec §7). The
 * source of truth is `docs/evals.md`, written by `uv run evals`; copy the
 * numbers from its results table here after each published run and set
 * `status: "published"` with the run date and golden-set version.
 *
 * Nothing here is computed by the web app.
 */

export type EvalRow = {
  config: string;
  /** Short description of the retrieval configuration. */
  detail: string;
  recallAt5: number;
  mrr: number;
  citationPrecision: number;
  latencyP50Ms: number;
  usdPerQuestion: number;
  /** The configuration the API serves. */
  shipped?: boolean;
};

export type EvalSample = {
  status: "placeholder" | "published";
  /** ISO date of the eval run, when published. */
  runDate?: string;
  goldenSet: string;
  questions: number;
  rows: EvalRow[];
  refusalCorrect: { correct: number; total: number };
};

export const evalsSample: EvalSample = {
  status: "published",
  runDate: "2026-10-05",
  goldenSet: "golden v1 (Expo SDK 57 and 58, React Native current); Voyage voyage-4-lite 1,024-d embeddings over all 5,031 chunks",
  questions: 40,
  rows: [
    {
      config: "vector",
      detail: "pgvector cosine top-40 (voyage-4-lite)",
      recallAt5: 0.94,
      mrr: 0.84,
      citationPrecision: 1.0,
      latencyP50Ms: 6700,
      usdPerQuestion: 0.00155,
      shipped: true,
    },
    {
      config: "full-text",
      detail: "Postgres tsvector top-40, ts_rank, API-name boost",
      recallAt5: 0.86,
      mrr: 0.69,
      citationPrecision: 1.0,
      latencyP50Ms: 3200,
      usdPerQuestion: 0.00118,
    },
    {
      config: "hybrid",
      detail: "vector ∪ full-text, RRF k=60 + API boost",
      recallAt5: 0.86,
      mrr: 0.7,
      citationPrecision: 0.98,
      latencyP50Ms: 5400,
      usdPerQuestion: 0.00148,
    },
    {
      config: "hybrid + rerank",
      detail: "RRF top-40 → rerank-2.5-lite top-8 (rerank rate-limited during this run, so it matched hybrid)",
      recallAt5: 0.86,
      mrr: 0.7,
      citationPrecision: 1.0,
      latencyP50Ms: 6500,
      usdPerQuestion: 0.00148,
    },
  ],
  refusalCorrect: { correct: 35, total: 35 },
};
