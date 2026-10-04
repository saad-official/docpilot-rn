import type { ReactNode } from "react";
import { CircleAlertIcon, CircleSlashIcon, LoaderCircleIcon, OctagonXIcon, ShieldCheckIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { compareVersionsDesc, formatCount, formatDate, formatDuration, formatUsd, versionLabel } from "@/lib/format";
import { citedNumbers } from "@/lib/markdown";
import { isStreaming, removedSet, type AnswerView } from "@/lib/turn";
import { cn } from "@/lib/utils";
import { AnswerProse } from "./answer-prose";
import { DiffTable } from "./diff-table";
import { SourcePanel } from "./source-panel";
import { VersionBadge } from "./version-badge";

function StatusLine({ view }: { view: AnswerView }) {
  const v = versionLabel(view.sdk, view.version);
  const base = "flex items-start gap-2 text-sm";
  if (view.status === "retrieving") {
    return (
      <p className={cn(base, "text-muted-foreground")}>
        <LoaderCircleIcon className="mt-0.5 size-4 shrink-0 motion-safe:animate-spin" aria-hidden="true" />
        Retrieving passages from the {v} docs…
      </p>
    );
  }
  if (view.status === "answering") {
    return (
      <p className={cn(base, "text-muted-foreground")}>
        <LoaderCircleIcon className="mt-0.5 size-4 shrink-0 motion-safe:animate-spin" aria-hidden="true" />
        {view.citations ? "Checking citations against the passages…" : "Writing from the retrieved passages…"}
      </p>
    );
  }
  if (view.status === "stopped") {
    return (
      <p className={cn(base, "text-muted-foreground")}>
        <OctagonXIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        Stopped. What is shown is incomplete and its citations were not verified.
      </p>
    );
  }
  return null;
}

function VerifierNote({ view }: { view: AnswerView }) {
  const c = view.citations;
  if (!c || view.status !== "done") return null;
  if (c.unsupported) {
    return (
      <div role="note" className="flex items-start gap-2.5 rounded-md border border-removed/55 bg-removed-wash px-3.5 py-3 text-sm text-removed-ink">
        <CircleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p>
          <strong className="font-semibold">Unsupported.</strong> No retrieved passage backs this answer, so treat it as a pointer to
          the docs, not as an answer.
        </p>
      </div>
    );
  }
  const removed = c.removed.length;
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <ShieldCheckIcon className="mt-px size-3.5 shrink-0 text-cite-ink" aria-hidden="true" />
      <span>
        {c.verified.length} citation{c.verified.length === 1 ? "" : "s"} verified against the retrieved passages
        {removed > 0 ? (
          <>
            {"; "}
            <span className="text-destructive">
              {removed} removed
            </span>{" "}
            because {removed === 1 ? "it" : "they"} could not be checked
          </>
        ) : null}
        .
      </span>
    </p>
  );
}

function Meta({ view }: { view: AnswerView }) {
  const parts: string[] = [];
  if (view.latency_ms !== undefined) parts.push(formatDuration(view.latency_ms));
  if (view.usage && view.usage.total_tokens > 0) parts.push(`${formatCount(view.usage.total_tokens)} tokens`);
  if (view.usage) parts.push(`${formatUsd(view.usage.usd)} at paid rates`);
  const date = formatDate(view.created_at);
  if (date) parts.push(date);
  if (parts.length === 0) return null;
  return (
    <p className="figure text-xs text-muted-foreground">
      <span className="sr-only">Answered in </span>
      {parts.join(" · ")}
    </p>
  );
}

/**
 * One answer as a document: question, version badge, the structured diff in
 * "What changed?" mode, the prose with citation chips, and the source panel.
 * Server-safe (no hooks), shared by the landing page, /ask and /q/[id].
 */
export function AnswerDocument({
  view,
  idPrefix,
  headingLevel = 2,
  actions,
  errorAction,
  className,
}: {
  view: AnswerView;
  idPrefix: string;
  headingLevel?: 1 | 2 | 3;
  /** Feedback and share controls, shown under a finished answer. */
  actions?: ReactNode;
  /** A retry control, shown inside the error box. */
  errorAction?: ReactNode;
  className?: string;
}) {
  const H = `h${headingLevel}` as "h1" | "h2" | "h3";
  const panelLevel = (headingLevel + 1) as 2 | 3 | 4;
  const streaming = isStreaming(view.status);
  const removed = removedSet(view.citations);
  const isDiff = view.mode === "diff" && !!view.compare_version;
  const [newer, older] = isDiff ? [view.version, view.compare_version!].sort(compareVersionsDesc) : [view.version, undefined];
  const titleId = `${idPrefix}-q`;

  return (
    <article aria-labelledby={titleId} aria-busy={streaming} className={cn("grid gap-8 lg:grid-cols-[minmax(0,1fr)_21rem] lg:gap-10", className)}>
      <div className="min-w-0 space-y-5">
        <header className="space-y-3">
          <p className="kicker">{isDiff ? "§ what changed?" : "§ answer"}</p>
          <H
            id={titleId}
            className={cn(
              "font-serif leading-snug font-semibold [overflow-wrap:anywhere]",
              headingLevel === 1 ? "text-3xl sm:text-4xl" : "text-2xl sm:text-[1.75rem]",
            )}
          >
            {view.question}
          </H>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {isDiff && older ? (
              <>
                <VersionBadge sdk={view.sdk} version={older} tone="before" title={`Older version: ${older}`} />
                <span aria-hidden="true">→</span>
                <span className="sr-only">compared with</span>
                <VersionBadge sdk={view.sdk} version={newer} tone="after" title={`Newer version: ${newer}`} />
                <span className="text-xs">
                  you are on <span className="figure text-version-ink">{versionLabel(view.sdk, view.version)}</span>
                </span>
              </>
            ) : (
              <>
                <VersionBadge sdk={view.sdk} version={view.version} tone="selected" />
                <span className="text-xs">answered from these docs only</span>
              </>
            )}
          </div>
        </header>

        <StatusLine view={view} />

        {isDiff && older ? (
          view.diff ? (
            <DiffTable
              diff={view.diff}
              sdk={view.sdk}
              olderVersion={older}
              newerVersion={newer}
              chunks={view.chunks}
              removed={removed}
              idPrefix={idPrefix}
            />
          ) : streaming ? (
            <div className="space-y-2 rounded-md border border-border bg-sheet p-4" aria-hidden="true">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : null
        ) : null}

        {view.answer !== "" || streaming ? (
          <AnswerProse
            text={view.answer}
            chunks={view.chunks}
            removed={removed}
            verified={!!view.citations}
            idPrefix={idPrefix}
            streaming={streaming && view.status === "answering"}
          />
        ) : null}

        {view.status === "error" && view.error ? (
          <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3.5">
            <p className="flex items-center gap-2 font-semibold text-destructive">
              <CircleSlashIcon className="size-4 shrink-0" aria-hidden="true" />
              {view.error.title}
            </p>
            <p className="mt-1 text-sm text-foreground/85">{view.error.message}</p>
            {view.error.hint ? <p className="mt-1 text-sm text-muted-foreground">{view.error.hint}</p> : null}
            {errorAction ? <div className="mt-3">{errorAction}</div> : null}
          </div>
        ) : null}

        <VerifierNote view={view} />

        {view.status === "done" || view.status === "stopped" ? (
          <footer className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t border-border pt-4">
            <Meta view={view} />
            {actions}
          </footer>
        ) : null}
      </div>

      <div className="min-w-0 lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
        <SourcePanel
          chunks={view.chunks}
          citations={view.citations}
          citedInText={citedNumbers(view.answer)}
          idPrefix={idPrefix}
          sdk={view.sdk}
          mode={view.mode}
          version={view.version}
          compareVersion={view.compare_version}
          headingLevel={panelLevel}
        />
      </div>
    </article>
  );
}
