"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowUpIcon, LoaderCircleIcon, RotateCcwIcon, SquareIcon } from "lucide-react";
import { AnswerDocument } from "@/components/answer/answer-document";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { getVersions, MAX_QUESTION_LENGTH, SDKS, streamAsk, type AskInput, type Mode, type Sdk, type Versions } from "@/lib/api";
import { API_URL } from "@/lib/config";
import { examplesFor, type ExampleQuestion } from "@/lib/examples";
import { formatCount, formatDate, sourceLabel, versionLabel } from "@/lib/format";
import {
  applyEvent,
  buildThread,
  cutOffTurn,
  failTurn,
  isStreaming,
  MAX_TURNS,
  newTurn,
  pushTurn,
  replaceTurn,
  stopTurn,
  toTurnError,
  type Turn,
  type TurnError,
} from "@/lib/turn";
import { cn } from "@/lib/utils";
import { FeedbackButtons } from "./feedback-buttons";
import { ShareLink } from "./share-link";

const label = "mb-1.5 block text-xs font-semibold tracking-wide text-muted-foreground uppercase";
const trigger = "h-10 w-full rounded-md bg-sheet text-sm data-[size=default]:h-10";

function asSdk(v: string | null): Sdk {
  return v === "react-native" ? "react-native" : "expo";
}

let keySeq = 0;
function nextKey() {
  keySeq += 1;
  return `t${Date.now().toString(36)}${keySeq}`;
}

/**
 * The ask tool: source, version and mode, a question, and the streamed answer
 * documents. The thread (last MAX_TURNS answers) lives only in this component.
 */
export function AskWorkspace() {
  const params = useSearchParams();
  const formId = useId();

  const [versions, setVersions] = useState<Versions | null>(null);
  const [versionsError, setVersionsError] = useState<TurnError | null>(null);
  const [loadKey, setLoadKey] = useState(0);

  const [sdk, setSdk] = useState<Sdk>(() => asSdk(params.get("sdk")));
  const [version, setVersion] = useState(() => params.get("v") ?? "");
  const [compare, setCompare] = useState(() => params.get("cmp") ?? "");
  const [mode, setMode] = useState<Mode>(() => (params.get("mode") === "diff" ? "diff" : "answer"));
  const [question, setQuestion] = useState(() => (params.get("q") ?? "").slice(0, MAX_QUESTION_LENGTH));
  const [fieldError, setFieldError] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    getVersions()
      .then((v) => {
        if (cancelled) return;
        setVersions(v);
        setVersionsError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setVersionsError(toTurnError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [loadKey]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Derived selection: an unknown or missing version falls back to the newest one.
  const sources = versions?.sources ?? [];
  const sourceNames: Sdk[] = sources.length > 0 ? SDKS.filter((s) => sources.some((x) => x.name === s)) : [...SDKS];
  const sourceInfo = sources.find((s) => s.name === sdk);
  const versionList = sourceInfo?.versions ?? [];
  const effectiveVersion = versionList.some((v) => v.version === version) ? version : (versionList[0]?.version ?? "");
  const selectedInfo = versionList.find((v) => v.version === effectiveVersion);
  const compareList = versionList.filter((v) => v.version !== effectiveVersion);
  const effectiveCompare = compareList.some((v) => v.version === compare) ? compare : (compareList[0]?.version ?? "");
  const diffAvailable = compareList.length > 0;
  const effectiveMode: Mode = mode === "diff" && diffAvailable ? "diff" : "answer";

  const current = turns[0];
  const busy = !!current && isStreaming(current.status);
  const ready = !!versions && effectiveVersion !== "";

  function ask(input: AskInput, replaceKey?: string) {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const key = nextKey();
    const base = replaceKey ? turns.filter((t) => t.key !== replaceKey) : turns;
    const thread = buildThread(base);
    const turn = newTurn(key, input);
    setTurns(pushTurn(base.map((t) => (isStreaming(t.status) ? stopTurn(t) : t)), turn));
    setAnnouncement(`Asking about ${sourceLabel(input.sdk)} ${versionLabel(input.sdk, input.version)}. Retrieving passages.`);
    const update = (fn: (t: Turn) => Turn) => setTurns((prev) => replaceTurn(prev, key, fn));

    streamAsk({ ...input, thread }, (ev) => {
      update((t) => applyEvent(t, ev));
      if (ev.kind === "retrieval") setAnnouncement(`${ev.chunks.length} passages retrieved. Writing the answer.`);
      if (ev.kind === "done") setAnnouncement("Answer complete.");
      if (ev.kind === "error") setAnnouncement(`The answer failed: ${ev.message ?? "error"}.`);
    }, ctrl.signal)
      .then(({ terminal }) => {
        if (!terminal && !ctrl.signal.aborted) {
          update(cutOffTurn);
          setAnnouncement("The answer stopped before it finished.");
        }
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        update((t) => failTurn(t, e));
        setAnnouncement(`Could not answer: ${toTurnError(e).message}`);
      })
      .finally(() => {
        if (abortRef.current === ctrl) abortRef.current = null;
      });
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const q = question.trim();
    if (q.length < 3) {
      setFieldError("Write a question of at least a few words.");
      textareaRef.current?.focus();
      return;
    }
    if (q.length > MAX_QUESTION_LENGTH) {
      setFieldError(`Keep the question under ${formatCount(MAX_QUESTION_LENGTH)} characters.`);
      textareaRef.current?.focus();
      return;
    }
    if (!ready) return;
    setFieldError(null);
    ask({
      question: q,
      sdk,
      version: effectiveVersion,
      mode: effectiveMode,
      compare_version: effectiveMode === "diff" ? effectiveCompare : undefined,
    });
  }

  function stop() {
    abortRef.current?.abort();
    abortRef.current = null;
    if (current) setTurns((prev) => replaceTurn(prev, current.key, stopTurn));
    setAnnouncement("Stopped.");
  }

  function newThread() {
    abortRef.current?.abort();
    abortRef.current = null;
    setTurns([]);
    setAnnouncement("Started a new thread.");
    textareaRef.current?.focus();
  }

  function pickExample(ex: ExampleQuestion) {
    setSdk(ex.sdk);
    setMode(ex.mode);
    // An example may prefer a version pair (the mock's diff fixture); only applied when both are indexed.
    const list = sources.find((s) => s.name === ex.sdk)?.versions ?? [];
    if (ex.prefer && list.some((v) => v.version === ex.prefer!.version) && list.some((v) => v.version === ex.prefer!.compare)) {
      setVersion(ex.prefer.version);
      setCompare(ex.prefer.compare);
    }
    setQuestion(ex.question);
    setFieldError(null);
    textareaRef.current?.focus();
  }

  const examples = examplesFor(sdk, effectiveMode);
  const remaining = MAX_QUESTION_LENGTH - question.length;

  return (
    <div className="space-y-12">
      <form
        id={formId}
        aria-label="Ask the docs"
        onSubmit={onSubmit}
        className="rounded-lg border border-border bg-sheet p-4 shadow-sheet sm:p-5"
        noValidate
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[10rem_12rem_auto_12rem]">
          <div>
            <label htmlFor={`${formId}-sdk`} className={label}>
              Source
            </label>
            <Select value={sdk} onValueChange={(v) => setSdk(asSdk(v))} disabled={busy}>
              <SelectTrigger id={`${formId}-sdk`} className={trigger}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper">
                {sourceNames.map((s) => (
                  <SelectItem key={s} value={s}>
                    {sourceLabel(s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label htmlFor={`${formId}-version`} className={label}>
              {effectiveMode === "diff" ? "Your version" : "Version"}
            </label>
            <Select value={effectiveVersion} onValueChange={setVersion} disabled={busy || versionList.length === 0}>
              <SelectTrigger id={`${formId}-version`} className={cn(trigger, "figure")}>
                <SelectValue placeholder={versionsError ? "unavailable" : "loading…"} />
              </SelectTrigger>
              <SelectContent position="popper">
                {versionList.map((v) => (
                  <SelectItem key={v.version} value={v.version} className="figure">
                    {versionLabel(sdk, v.version)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedInfo ? (
              <p className="figure mt-1 text-xs text-muted-foreground">
                {selectedInfo.version}
                {selectedInfo.chunk_count !== undefined ? ` · ${formatCount(selectedInfo.chunk_count)} chunks` : ""}
                {selectedInfo.ingested_at ? ` · ${formatDate(selectedInfo.ingested_at)}` : ""}
              </p>
            ) : null}
          </div>

          <fieldset className="min-w-0">
            <legend className={label}>Mode</legend>
            <div className="grid h-10 grid-cols-2 rounded-md border border-input bg-background p-0.5">
              {(
                [
                  { value: "answer", text: "Answer" },
                  { value: "diff", text: "What changed?" },
                ] as const
              ).map((m) => {
                const disabled = busy || (m.value === "diff" && !diffAvailable);
                return (
                  <label
                    key={m.value}
                    className={cn(
                      "relative flex cursor-pointer items-center justify-center rounded-[0.3rem] px-3 text-sm font-medium whitespace-nowrap has-focus-visible:outline-2 has-focus-visible:outline-offset-1 has-focus-visible:outline-cite",
                      effectiveMode === m.value ? "bg-primary text-primary-foreground" : "text-foreground/75 hover:text-foreground",
                      disabled && "cursor-not-allowed opacity-50",
                    )}
                  >
                    <input
                      type="radio"
                      name={`${formId}-mode`}
                      value={m.value}
                      checked={effectiveMode === m.value}
                      disabled={disabled}
                      onChange={() => setMode(m.value)}
                      className="sr-only"
                    />
                    {m.text}
                  </label>
                );
              })}
            </div>
            {!diffAvailable && versions ? (
              <p className="mt-1 text-xs text-muted-foreground">{sourceLabel(sdk)} is indexed at one version.</p>
            ) : null}
          </fieldset>

          {effectiveMode === "diff" ? (
            <div>
              <label htmlFor={`${formId}-compare`} className={label}>
                Compare with
              </label>
              <Select value={effectiveCompare} onValueChange={setCompare} disabled={busy}>
                <SelectTrigger id={`${formId}-compare`} className={cn(trigger, "figure")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent position="popper">
                  {compareList.map((v) => (
                    <SelectItem key={v.version} value={v.version} className="figure">
                      {versionLabel(sdk, v.version)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>

        {versionsError ? (
          <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 px-3.5 py-3 text-sm">
            <p>
              <strong className="font-semibold text-destructive">Could not load the indexed versions.</strong>{" "}
              <span className="text-foreground/85">{versionsError.message}</span>
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setVersionsError(null);
                setLoadKey((k) => k + 1);
              }}
            >
              <RotateCcwIcon aria-hidden="true" />
              Retry
            </Button>
          </div>
        ) : null}

        <div className="mt-4">
          <label htmlFor={`${formId}-q`} className={label}>
            Question
          </label>
          <Textarea
            id={`${formId}-q`}
            ref={textareaRef}
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value.slice(0, MAX_QUESTION_LENGTH));
              if (fieldError) setFieldError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            rows={3}
            maxLength={MAX_QUESTION_LENGTH}
            placeholder={
              effectiveMode === "diff"
                ? "Ask something that may differ between the two versions…"
                : "Ask about an API, a config key, a guide…"
            }
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={`${formId}-q-help${fieldError ? ` ${formId}-q-error` : ""}`}
            className="min-h-24 resize-y rounded-md bg-background px-3 py-2.5 text-[0.9375rem] leading-relaxed md:text-[0.9375rem]"
          />
          <div className="mt-1.5 flex flex-wrap items-start justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <p id={`${formId}-q-help`}>
              Answers come only from the selected version&apos;s docs.{" "}
              <span className="hidden sm:inline">
                <kbd className="figure">Ctrl</kbd>+<kbd className="figure">Enter</kbd> to ask.
              </span>
            </p>
            <p className={cn("figure", remaining < 100 && "text-removed-ink")} aria-hidden={remaining >= 100}>
              {question.length}/{MAX_QUESTION_LENGTH}
            </p>
          </div>
          {fieldError ? (
            <p id={`${formId}-q-error`} className="mt-1.5 text-sm font-medium text-destructive">
              {fieldError}
            </p>
          ) : null}
        </div>

        <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p id={`${formId}-ex`} className="mb-1.5 text-xs text-muted-foreground">
              Try one:
            </p>
            <ul aria-labelledby={`${formId}-ex`} className="flex flex-wrap gap-2">
              {examples.map((ex) => (
                <li key={ex.question}>
                  <button
                    type="button"
                    onClick={() => pickExample(ex)}
                    disabled={busy}
                    className="rounded-md border border-border bg-background px-2.5 py-1 text-left text-xs text-foreground/85 hover:border-cite/40 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cite disabled:opacity-50"
                  >
                    {ex.mode === "diff" ? <span className="figure mr-1 text-added-ink">Δ</span> : null}
                    {ex.question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {turns.length > 0 && !busy ? (
              <Button type="button" variant="ghost" onClick={newThread} className="h-10">
                New thread
              </Button>
            ) : null}
            {busy ? (
              <Button type="button" variant="outline" onClick={stop} className="h-10 px-4">
                <SquareIcon aria-hidden="true" />
                Stop
              </Button>
            ) : (
              <Button type="submit" disabled={!ready} className="h-10 px-5 font-semibold">
                {versions || versionsError ? <ArrowUpIcon aria-hidden="true" /> : <LoaderCircleIcon className="motion-safe:animate-spin" aria-hidden="true" />}
                {effectiveMode === "diff" ? "Compare" : "Ask"}
              </Button>
            )}
          </div>
        </div>
      </form>

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>

      {current ? (
        <AnswerDocument
          key={current.key}
          view={current}
          idPrefix={current.key}
          headingLevel={2}
          actions={
            current.question_id ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <ShareLink questionId={current.question_id} />
                <FeedbackButtons questionId={current.question_id} />
              </div>
            ) : null
          }
          errorAction={
            current.error?.code !== "invalid_input" ? (
              <Button type="button" variant="outline" size="sm" onClick={() => ask(current.input, current.key)}>
                <RotateCcwIcon aria-hidden="true" />
                Try again
              </Button>
            ) : null
          }
        />
      ) : (
        <EmptyState />
      )}

      {turns.length > 1 ? (
        <section aria-labelledby={`${formId}-earlier`} className="space-y-3 border-t border-border pt-8">
          <h2 id={`${formId}-earlier`} className="font-serif text-lg font-semibold">
            Earlier in this thread
          </h2>
          <p className="text-sm text-muted-foreground">
            The last {MAX_TURNS} questions are kept in this tab and sent with the next one, so a follow-up like &ldquo;and on
            Android?&rdquo; is understood. The thread lives in this tab only.
          </p>
          <ul className="space-y-3">
            {turns.slice(1).map((t) => (
              <li key={t.key}>
                <details className="group rounded-md border border-border bg-sheet">
                  <summary className="flex cursor-pointer list-none items-baseline gap-3 rounded-md px-4 py-3 [&::-webkit-details-marker]:hidden">
                    <span aria-hidden="true" className="figure text-muted-foreground group-open:rotate-90 motion-safe:transition-transform">
                      ›
                    </span>
                    <span className="min-w-0 flex-1 font-medium [overflow-wrap:anywhere]">{t.question}</span>
                    <span className="figure shrink-0 text-xs text-version-ink">{versionLabel(t.sdk, t.version)}</span>
                  </summary>
                  <div className="border-t border-border px-4 py-5">
                    <AnswerDocument
                      view={t}
                      idPrefix={t.key}
                      headingLevel={3}
                      actions={t.question_id ? <ShareLink questionId={t.question_id} /> : null}
                    />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="figure text-xs text-muted-foreground">API: {API_URL}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <section aria-label="How answers look" className="grid gap-6 rounded-lg border border-dashed border-border p-5 sm:grid-cols-3 sm:p-6">
      {[
        { k: "1", t: "Pinned to a version", b: "Passages come only from the docs for the version you picked, plus the unversioned guides." },
        { k: "2", t: "Cited inline", b: "Numbered chips link to the passage on the right, with the quoted sentence highlighted." },
        { k: "3", t: "Checked, not trusted", b: "A citation that cannot be matched to a retrieved passage is removed and listed, struck through." },
      ].map((x) => (
        <div key={x.k} className="space-y-1.5">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <span className="figure inline-flex size-5 items-center justify-center rounded-[0.3rem] border border-cite/40 bg-cite-wash text-[0.7rem] text-cite-ink">
              {x.k}
            </span>
            {x.t}
          </p>
          <p className="text-sm text-muted-foreground">{x.b}</p>
        </div>
      ))}
    </section>
  );
}
