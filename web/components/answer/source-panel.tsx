import { ArrowUpRightIcon, CircleSlashIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { Citations, Mode, RetrievedChunk } from "@/lib/api";
import { compareVersionsDesc, formatScore, shortUrl } from "@/lib/format";
import { splitOnQuote } from "@/lib/highlight";
import { cn } from "@/lib/utils";
import { sourceAnchor } from "./citation-chip";
import { VersionBadge, type VersionTone } from "./version-badge";

type CardState = "cited" | "pending" | "retrieved" | "removed";

function versionTone(chunkVersion: string, mode: Mode, version: string, compareVersion?: string): VersionTone {
  if (mode === "diff" && compareVersion) {
    const [newer] = [version, compareVersion].sort(compareVersionsDesc);
    if (chunkVersion === newer) return "after";
    if (chunkVersion === version || chunkVersion === compareVersion) return "before";
    return "plain";
  }
  return chunkVersion === version ? "selected" : "plain";
}

function SourceCard({
  chunk,
  idPrefix,
  sdk,
  tone,
  state,
  quote,
  removedReason,
}: {
  chunk: RetrievedChunk;
  idPrefix: string;
  sdk: string;
  tone: VersionTone;
  state: CardState;
  quote?: string;
  removedReason?: string;
}) {
  const segments = splitOnQuote(chunk.snippet, state === "cited" ? quote : undefined);
  const removed = state === "removed";
  return (
    <li>
      <article
        id={sourceAnchor(idPrefix, chunk.n)}
        aria-label={`Source ${chunk.n}: ${chunk.title}`}
        className={cn(
          "source-card rounded-md border bg-sheet p-3.5 motion-safe:transition-[outline-color]",
          state === "cited" ? "border-cite/30" : "border-border",
          state === "retrieved" && "bg-transparent",
        )}
      >
        <div className="flex items-start gap-2.5">
          <span
            aria-hidden="true"
            className={cn(
              "figure mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-[0.3rem] border px-1 text-[0.7rem] font-semibold",
              state === "cited" && "border-cite/40 bg-cite-wash text-cite-ink",
              state === "pending" && "border-cite/45 text-cite-ink",
              state === "retrieved" && "border-border text-pencil",
              removed && "border-destructive/40 text-destructive line-through",
            )}
          >
            {chunk.n}
          </span>
          <div className="min-w-0 flex-1">
            <p className={cn("text-sm leading-snug font-semibold [overflow-wrap:anywhere]", removed && "line-through decoration-destructive/60")}>
              {chunk.title}
            </p>
            {chunk.heading_path ? (
              <p className="mt-0.5 text-xs leading-snug text-muted-foreground [overflow-wrap:anywhere]">{chunk.heading_path}</p>
            ) : null}
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
          {chunk.version ? <VersionBadge sdk={sdk} version={chunk.version} tone={tone} withSource={false} className="h-5 text-[0.7rem]" /> : null}
          {chunk.score !== undefined ? (
            <span className="figure text-[0.7rem] text-muted-foreground" title="Retrieval score after fusion and rerank">
              score {formatScore(chunk.score)}
            </span>
          ) : null}
          {state === "cited" ? <span className="text-[0.7rem] font-semibold text-cite-ink">verified</span> : null}
        </div>

        {chunk.snippet ? (
          <blockquote
            className={cn(
              "mt-2.5 border-l-2 pl-3 text-[0.8125rem] leading-relaxed text-foreground/85 [overflow-wrap:anywhere]",
              state === "cited" ? "border-cite/50" : "border-border",
              removed && "text-muted-foreground line-through decoration-muted-foreground/50",
            )}
          >
            {segments.map((s, i) =>
              s.mark ? (
                <mark key={i} className="rounded-[2px] bg-cite-mark px-0.5 text-foreground [box-decoration-break:clone]">
                  <span className="sr-only">Quoted: </span>
                  {s.text}
                </mark>
              ) : (
                <span key={i}>{s.text}</span>
              ),
            )}
          </blockquote>
        ) : null}

        {removed && removedReason ? (
          <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
            <CircleSlashIcon className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            <span>Citation removed by the verifier: {removedReason}</span>
          </p>
        ) : null}

        {chunk.url ? (
          <a
            href={chunk.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2.5 inline-flex max-w-full items-center gap-1 text-xs font-medium text-cite-ink underline decoration-cite-ink/30 underline-offset-3 hover:decoration-cite-ink"
          >
            <span className="figure truncate">{shortUrl(chunk.url)}</span>
            <ArrowUpRightIcon className="size-3 shrink-0" aria-hidden="true" />
            <span className="sr-only">(opens the docs in a new tab)</span>
          </a>
        ) : null}
      </article>
    </li>
  );
}

function PanelSkeleton() {
  return (
    <ul className="space-y-3" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <li key={i} className="rounded-md border border-border bg-sheet p-3.5">
          <div className="flex gap-2.5">
            <Skeleton className="size-5 rounded-[0.3rem]" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
          <Skeleton className="mt-3 h-3 w-full" />
          <Skeleton className="mt-1.5 h-3 w-5/6" />
        </li>
      ))}
    </ul>
  );
}

const groupLabel = "figure mb-2 text-[0.7rem] font-semibold tracking-wide text-muted-foreground uppercase";

/**
 * The right-hand source panel: retrieved passages appear first (skeletons
 * until the retrieval event), then the verifier sorts them into cited (quote
 * highlighted), removed (struck, with the reason) and also-retrieved.
 */
export function SourcePanel({
  chunks,
  citations,
  citedInText,
  idPrefix,
  sdk,
  mode,
  version,
  compareVersion,
  headingLevel = 3,
}: {
  chunks: RetrievedChunk[] | undefined;
  citations: Citations | undefined;
  /** Citation numbers found in the answer so far, used before the verifier reports. */
  citedInText: number[];
  idPrefix: string;
  sdk: string;
  mode: Mode;
  version: string;
  compareVersion?: string;
  headingLevel?: 2 | 3 | 4;
}) {
  const H = `h${headingLevel}` as "h2" | "h3" | "h4";
  const titleId = `${idPrefix}-sources-title`;
  const tone = (c: RetrievedChunk) => versionTone(c.version, mode, version, compareVersion);

  const verifiedByN = new Map((citations?.verified ?? []).map((v) => [v.n, v]));
  const removedByN = new Map((citations?.removed ?? []).map((r) => [r.n, r]));
  const citedNs = citations ? new Set(verifiedByN.keys()) : new Set(citedInText);
  const list = chunks ?? [];
  const cited = list.filter((c) => citedNs.has(c.n) && !removedByN.has(c.n));
  const removedChunks = list.filter((c) => removedByN.has(c.n));
  const removedOrphans = [...removedByN.values()].filter((r) => !list.some((c) => c.n === r.n));
  const rest = list.filter((c) => !citedNs.has(c.n) && !removedByN.has(c.n));

  return (
    <section aria-labelledby={titleId} className="min-w-0">
      <div className="mb-3 flex items-baseline justify-between gap-3 border-b border-border pb-2">
        <H id={titleId} className="font-serif text-base font-semibold">
          Sources
        </H>
        <span className="figure text-xs text-muted-foreground" aria-live="polite">
          {chunks === undefined
            ? "retrieving…"
            : citations
              ? `${cited.length} cited · ${list.length} retrieved`
              : `${list.length} retrieved`}
        </span>
      </div>

      {chunks === undefined ? (
        <>
          <p className="sr-only">Retrieving passages from the docs.</p>
          <PanelSkeleton />
        </>
      ) : list.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          No passages matched this question in the selected version.
        </p>
      ) : (
        <div className="space-y-5">
          {cited.length > 0 ? (
            <div>
              <p className={groupLabel}>{citations ? "Cited" : "Cited so far"}</p>
              <ul className="space-y-3">
                {cited.map((c) => (
                  <SourceCard
                    key={c.id}
                    chunk={c}
                    idPrefix={idPrefix}
                    sdk={sdk}
                    tone={tone(c)}
                    state={citations ? "cited" : "pending"}
                    quote={verifiedByN.get(c.n)?.quote}
                  />
                ))}
              </ul>
            </div>
          ) : null}

          {removedChunks.length > 0 || removedOrphans.length > 0 ? (
            <div>
              <p className={groupLabel}>Removed by the verifier</p>
              <ul className="space-y-3">
                {removedChunks.map((c) => (
                  <SourceCard
                    key={c.id}
                    chunk={c}
                    idPrefix={idPrefix}
                    sdk={sdk}
                    tone={tone(c)}
                    state="removed"
                    removedReason={removedByN.get(c.n)?.reason}
                  />
                ))}
                {removedOrphans.map((r) => (
                  <li key={r.n} id={sourceAnchor(idPrefix, r.n)} className="source-card rounded-md border border-dashed border-destructive/35 p-3">
                    <p className="flex items-start gap-2 text-xs text-destructive">
                      <span className="figure font-semibold line-through">[{r.n}]</span>
                      <span>{r.reason}</span>
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {rest.length > 0 ? (
            cited.length > 0 && citations ? (
              <details className="group">
                <summary className={cn(groupLabel, "mb-0 cursor-pointer list-none rounded-sm select-none [&::-webkit-details-marker]:hidden")}>
                  <span aria-hidden="true" className="mr-1 inline-block group-open:rotate-90 motion-safe:transition-transform">
                    ›
                  </span>
                  Also retrieved, not cited ({rest.length})
                </summary>
                <ul className="mt-2 space-y-3">
                  {rest.map((c) => (
                    <SourceCard key={c.id} chunk={c} idPrefix={idPrefix} sdk={sdk} tone={tone(c)} state="retrieved" />
                  ))}
                </ul>
              </details>
            ) : (
              <div>
                <p className={groupLabel}>{cited.length > 0 ? "Also retrieved" : "Retrieved"}</p>
                <ul className="space-y-3">
                  {rest.map((c) => (
                    <SourceCard key={c.id} chunk={c} idPrefix={idPrefix} sdk={sdk} tone={tone(c)} state="retrieved" />
                  ))}
                </ul>
              </div>
            )
          ) : null}
        </div>
      )}
    </section>
  );
}
