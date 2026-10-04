/**
 * The retrieval comparison table shown on the landing page (spec §7). The
 * source of truth is `docs/evals.md`, written by `uv run evals`; copy the
 * numbers from its results table here after each published run and set
 * `status: "published"` with the run date and golden-set version.
 *
 * Only configurations that were actually measured appear here. The vector,
 * hybrid and hybrid+rerank rows are added once the corpus is fully embedded
 * (Gemini's free tier embeds 1,000 chunks a day); until then the API serves
 * hybrid retrieval where vectors exist and full-text elsewhere.
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
  goldenSet: "golden v1 (Expo SDK 57 and 58, React Native current); full-text config measured, vector configs pending full embedding",
  questions: 40,
  rows: [
    {
      config: "full-text",
      detail: "Postgres tsvector top-40, ts_rank, exact API-name boost",
      recallAt5: 0.86,
      mrr: 0.69,
      citationPrecision: 0.99,
      latencyP50Ms: 6400,
      usdPerQuestion: 0.00109,
      shipped: true,
    },
  ],
  refusalCorrect: { correct: 29, total: 35 },
};
