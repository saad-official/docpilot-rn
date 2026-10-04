export const REPO_URL = "https://github.com/saad-official/docpilot-rn";
export const JOURNEY_URL = "https://github.com/saad-official/ai-engineering-journey";
export const SERIES_URL = "https://github.com/saad-official/vibe-build-series";
export const EVALS_DOC_URL = `${REPO_URL}/blob/main/docs/evals.md`;
export const EXPO_REPO_URL = "https://github.com/expo/expo";
export const EXPO_LICENSE_URL = "https://github.com/expo/expo/blob/main/LICENSE";
export const RN_DOCS_REPO_URL = "https://github.com/facebook/react-native-website";
export const CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/";

export const links = {
  repo: REPO_URL,
  journey: JOURNEY_URL,
  series: SERIES_URL,
  evals: EVALS_DOC_URL,
  ask: "/ask",
  docs: "/docs",
  howItWorks: "/#how-it-works",
  versions: "/#versions",
  evalsSection: "/#evals",
} as const;

/** Page container: 16px gutter on phones. */
export const container = "mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8";

/** Inline text link: indigo, underlined, stronger on hover. Focus comes from the global a:focus-visible rule. */
export const textLink =
  "text-cite-ink underline decoration-cite-ink/35 decoration-1 underline-offset-4 hover:decoration-cite-ink motion-safe:transition-colors";

/** Primary call to action: graphite slab on paper. */
export const ctaPrimary =
  "inline-flex h-11 items-center justify-center gap-2 rounded-md bg-primary px-5 text-[0.9375rem] font-semibold text-primary-foreground hover:bg-primary/88 motion-safe:transition-colors focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-cite";

export const ctaSecondary =
  "inline-flex h-11 items-center justify-center gap-2 rounded-md border border-input bg-sheet px-5 text-[0.9375rem] font-semibold text-foreground hover:bg-muted motion-safe:transition-colors focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-cite";
