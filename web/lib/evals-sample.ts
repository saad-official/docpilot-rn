/**
 * The retrieval comparison table shown on the landing page (spec §7). The
 * source of truth is `docs/evals.md`, written by `uv run evals`; copy the
 * numbers from its results table here after each published run and set
 * `status: "published"` with the run date and golden-set version.
 *
 * Until the first run is published these are placeholder figures, and the page
 * says so in the table caption. Nothing here is computed by the web app.
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
  status: "placeholder",
  runDate: undefined,
  goldenSet: "golden v1 (Expo SDK 57 and 58, React Native current)",
  questions: 40,
  rows: [
    { config: "vector", detail: "pgvector cosine top-40", recallAt5: 0.71, mrr: 0.58, citationPrecision: 0.9, latencyP50Ms: 2300, usdPerQuestion: 0.0008 },
    { config: "full-text", detail: "Postgres tsvector top-40", recallAt5: 0.64, mrr: 0.55, citationPrecision: 0.88, latencyP50Ms: 2200, usdPerQuestion: 0.0008 },
    { config: "hybrid", detail: "vector ∪ full-text, RRF k=60", recallAt5: 0.8, mrr: 0.66, citationPrecision: 0.92, latencyP50Ms: 2400, usdPerQuestion: 0.0008 },
    {
      config: "hybrid + rerank",
      detail: "RRF top-40 → rerank-2.5-lite top-8",
      recallAt5: 0.87,
      mrr: 0.76,
      citationPrecision: 0.95,
      latencyP50Ms: 2800,
      usdPerQuestion: 0.0009,
      shipped: true,
    },
  ],
  refusalCorrect: { correct: 4, total: 4 },
};
