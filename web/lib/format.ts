/** Formatting shared by the ask page, the stored-question page, the landing page and tests. */

const usdFull = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Dollars at the precision a single RAG question needs: $0.00042, $0.0037, $1.20. */
export function formatUsd(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0) return "$0.00";
  if (usd < 0.00001) return "<$0.00001";
  if (usd < 0.001) return `$${usd.toFixed(5)}`;
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return usdFull.format(usd);
}

const int = new Intl.NumberFormat("en-US");
export function formatCount(n: number): string {
  return Number.isFinite(n) ? int.format(Math.round(n)) : "0";
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m} min ${s} s`;
}

/** Retrieval scores: fused/rerank scores are small floats; show three decimals. */
export function formatScore(score: number | undefined): string {
  if (score === undefined || !Number.isFinite(score)) return "";
  return score.toFixed(3);
}

/** 0.917 -> "91.7%". */
export function formatPercent(v: number, digits = 1): string {
  if (!Number.isFinite(v)) return "n/a";
  return `${(v * 100).toFixed(digits)}%`;
}

const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** ISO timestamp -> "4 Oct 2026" (UTC, so server and client agree). Empty for junk. */
export function formatDate(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : dateFmt.format(d);
}

export const SOURCE_LABELS: Record<string, string> = {
  expo: "Expo",
  "react-native": "React Native",
};

export function sourceLabel(sdk: string): string {
  return SOURCE_LABELS[sdk] ?? sdk;
}

/**
 * Human label for a docs version. Expo versions are directories like
 * `v58.0.0`, which developers call "SDK 58"; anything else is shown as given.
 */
export function versionLabel(sdk: string, version: string): string {
  const v = version.trim();
  if (v === "") return "";
  if (sdk === "expo") {
    const m = v.match(/^v?(\d+)\.0\.0$/);
    if (m) return `SDK ${m[1]}`;
    if (v === "unversioned") return "guides";
    if (v === "latest") return "latest";
  }
  if (sdk === "react-native" && /^\d+\.\d+/.test(v)) return v.replace(/\.0$/, "");
  return v;
}

/** Order versions newest first: numeric segments compared, non-numeric versions last. */
export function compareVersionsDesc(a: string, b: string): number {
  const parse = (s: string) => {
    const m = s.match(/\d+(?:\.\d+)*/);
    return m ? m[0].split(".").map(Number) : null;
  };
  const pa = parse(a);
  const pb = parse(b);
  if (!pa && !pb) return a.localeCompare(b);
  if (!pa) return 1;
  if (!pb) return -1;
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pb[i] ?? 0) - (pa[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

/** Host and path of a docs URL, for compact display: docs.expo.dev/versions/v58.0.0/sdk/notifications */
export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname.replace(/\/$/, "")}`;
  } catch {
    return url;
  }
}
