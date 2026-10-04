import Link from "next/link";
import { ArrowRightIcon } from "lucide-react";
import { AnswerDocument } from "@/components/answer/answer-document";
import { Faq } from "@/components/marketing/faq";
import { StoredQuestionSchema } from "@/lib/api";
import { evalsSample } from "@/lib/evals-sample";
import { formatDate, formatDuration, formatPercent, formatUsd } from "@/lib/format";
import { storedQuestions } from "@/lib/mock";
import {
  CC_BY_URL,
  container,
  ctaPrimary,
  ctaSecondary,
  EXPO_LICENSE_URL,
  EXPO_REPO_URL,
  links,
  RN_DOCS_REPO_URL,
  textLink,
} from "@/lib/site";
import { storedToView, type AnswerView } from "@/lib/turn";
import { cn } from "@/lib/utils";

/** Static examples: the mock fixtures, parsed through the same contract as live answers. */
function example(id: string): AnswerView {
  const view = storedToView(StoredQuestionSchema.parse(storedQuestions[id]));
  return { ...view, created_at: undefined, question_id: undefined };
}
const heroExample = example("demo-notifications");
const diffExample = example("demo-diff");

const STEPS: { name: string; where: string; sentence: string }[] = [
  {
    name: "ingest",
    where: "CLI, offline",
    sentence: "Pulls the docs at a pinned commit from expo/expo and react-native-website. Never runs from the web.",
  },
  {
    name: "chunk",
    where: "structure-aware",
    sentence: "Splits on headings, keeps code blocks and tables whole, and records the heading path and anchor of every chunk.",
  },
  {
    name: "embed",
    where: "one model per corpus",
    sentence: "Embeds each chunk once, cached by content hash, so re-ingesting a version only pays for what changed.",
  },
  {
    name: "hybrid retrieve",
    where: "pgvector + full text",
    sentence: "Vector search and Postgres full text, both filtered to your version, fused with reciprocal rank fusion.",
  },
  {
    name: "rerank",
    where: "cross-encoder",
    sentence: "A reranker reads the top 40 against the question and keeps the best 8. Exact API names get a boost.",
  },
  {
    name: "answer",
    where: "streamed",
    sentence: "The model sees only those passages, numbered, and must cite them as [n] or say what is missing.",
  },
  {
    name: "verify citations",
    where: "plain code",
    sentence: "Every [n] must map to a retrieved passage and every quote must appear in it. Failures are removed and shown.",
  },
];

function SectionHead({ mark, id, title, children }: { mark: string; id: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="max-w-2xl space-y-3">
      <p className="kicker" aria-hidden="true">
        § {mark}
      </p>
      <h2 id={id} className="font-serif text-3xl leading-tight font-semibold sm:text-[2.25rem]">
        {title}
      </h2>
      {children ? <div className="space-y-3 text-[1.0625rem] leading-relaxed text-foreground/80">{children}</div> : null}
    </div>
  );
}

const askExampleHref = `/ask?${new URLSearchParams({ q: heroExample.question, sdk: "expo" }).toString()}`;

export default function Home() {
  const evals = evalsSample;
  const published = evals.status === "published";
  return (
    <>
      {/* Hero */}
      <section aria-labelledby="hero-title" className="border-b border-border">
        <div className={cn(container, "pt-12 pb-10 sm:pt-16")}>
          <div className="max-w-3xl space-y-5">
            <p className="kicker">§ 1 · Expo and React Native, answered for your version</p>
            <h1 id="hero-title" className="font-serif text-4xl leading-[1.1] font-semibold sm:text-5xl lg:text-[3.5rem]">
              The answer for the SDK you are on, with the page to prove it.
            </h1>
            <p className="max-w-2xl text-lg leading-relaxed text-foreground/80">
              Pick your Expo SDK version and ask. DocPilot answers only from that version&apos;s docs, cites every claim with a
              numbered link to the exact heading, and checks each citation against the passage before it shows it.
            </p>
            <div className="flex flex-wrap gap-3 pt-1">
              <Link href={links.ask} className={ctaPrimary}>
                Ask the docs
                <ArrowRightIcon className="size-4" aria-hidden="true" />
              </Link>
              <Link href={links.howItWorks} className={ctaSecondary}>
                How it works
              </Link>
            </div>
          </div>
        </div>

        <div className={cn(container, "pb-14")}>
          <div className="rounded-lg border border-border bg-sheet p-4 shadow-sheet sm:p-6 lg:p-8">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
              <p className="figure text-xs text-muted-foreground">example · answered from the Expo SDK 58 docs</p>
              <Link href={askExampleHref} className={cn(textLink, "text-sm")}>
                Ask it yourself
              </Link>
            </div>
            <AnswerDocument view={heroExample} idPrefix="hero" headingLevel={2} />
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" aria-labelledby="how-title" className="scroll-mt-6 border-b border-border">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead mark="2 · how it works" id="how-title" title="Seven steps, and the last one is not a model.">
            <p>
              Retrieval-augmented generation with the parts that usually get skipped: structure-aware chunks, hybrid search,
              a reranker, and a deterministic check on what the model claims to cite.
            </p>
          </SectionHead>
          <ol className="mt-10 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.name} className="bg-sheet p-5">
                <p className="figure flex items-baseline gap-2 text-sm">
                  <span className="text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                  <span className={cn("font-semibold", i === STEPS.length - 1 ? "text-cite-ink" : "text-foreground")}>{s.name}</span>
                </p>
                <p className="figure mt-1 text-xs text-muted-foreground">{s.where}</p>
                <p className="mt-3 text-sm leading-relaxed text-foreground/85">{s.sentence}</p>
              </li>
            ))}
            <li className="flex flex-col justify-between gap-4 bg-term p-5 text-term-fg">
              <p className="figure text-xs leading-relaxed text-term-dim">
                <span className="text-term-green">✓</span> [1] chunk c_8f12a0, quote found
                <br />
                <span className="text-term-green">✓</span> [2] chunk c_8f12b7, quote found
                <br />
                <span className="text-term-green">✓</span> [3] chunk c_8f13c4, quote found
                <br />
                <span className="text-term-amber">✗</span> [7] no such passage → removed
              </p>
              <p className="text-sm text-term-fg/90">What the verifier decided for the example answer above.</p>
            </li>
          </ol>
        </div>
      </section>

      {/* Version pinning */}
      <section id="versions" aria-labelledby="versions-title" className="scroll-mt-6 border-b border-border">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead mark="3 · version pinning" id="versions-title" title="The same question, two versions, different answers.">
            <p>
              In SDK 52 the notification handler returned <code className="figure text-[0.9em]">shouldShowAlert</code>. SDK 53
              deprecated it. A search engine hands you whichever page ranks first; DocPilot answers for the version you picked,
              and <strong className="font-semibold">What changed?</strong> retrieves from both versions and lays the
              difference out with citations to each.
            </p>
          </SectionHead>
          <div className="mt-10 rounded-lg border border-border bg-sheet p-4 shadow-sheet sm:p-6 lg:p-8">
            <AnswerDocument view={diffExample} idPrefix="pin" headingLevel={3} />
          </div>
        </div>
      </section>

      {/* Evals */}
      <section id="evals" aria-labelledby="evals-title" className="scroll-mt-6 border-b border-border">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead mark="4 · evals" id="evals-title" title="Measured, not asserted.">
            <p>
              A golden set of {evals.questions} questions with expected source pages, including version-sensitive questions and
              ones the docs cannot answer. Retrieval is scored by code (recall@5, MRR); citations by the verifier. The full
              report, with the configuration comparison and an LLM-judge score kept separate, is{" "}
              <a href={links.evals} className={textLink}>
                docs/evals.md
              </a>{" "}
              in the repository.
            </p>
          </SectionHead>

          <p id="evals-caption" className="mt-10 mb-3 max-w-2xl text-sm text-muted-foreground">
            {published ? (
              <>
                Latest published numbers: {evals.goldenSet}, run {formatDate(evals.runDate)}. Source:{" "}
                <a href={links.evals} className={textLink}>
                  docs/evals.md
                </a>
                .
              </>
            ) : (
              <>
                <strong className="font-semibold text-removed-ink">Placeholder figures until the first eval run.</strong> They
                show the shape of the report; the latest published numbers live in{" "}
                <a href={links.evals} className={textLink}>
                  docs/evals.md
                </a>
                .
              </>
            )}
          </p>
          <div
            className="overflow-x-auto rounded-lg border border-border bg-sheet focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cite"
            tabIndex={0}
            role="region"
            aria-labelledby="evals-title"
          >
            <table className="w-full min-w-[40rem] border-collapse text-left text-sm" aria-describedby="evals-caption">
              <caption className="sr-only">Retrieval configurations compared on the golden set</caption>
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Retrieval
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    recall@5
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    MRR
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    citation precision
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    p50 latency
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    cost / question
                  </th>
                </tr>
              </thead>
              <tbody>
                {evals.rows.map((r) => (
                  <tr key={r.config} className={cn("border-b border-border last:border-b-0", r.shipped && "bg-cite-wash/50")}>
                    <th scope="row" className="px-4 py-3 font-normal">
                      <span className="font-semibold">{r.config}</span>
                      {r.shipped ? (
                        <span className="figure ml-2 rounded-sm border border-cite/40 px-1.5 py-px text-[0.68rem] text-cite-ink">
                          served
                        </span>
                      ) : null}
                      <span className="figure block text-xs text-muted-foreground">{r.detail}</span>
                    </th>
                    <td className="figure px-4 py-3 text-right">{formatPercent(r.recallAt5, 0)}</td>
                    <td className="figure px-4 py-3 text-right">{r.mrr.toFixed(2)}</td>
                    <td className="figure px-4 py-3 text-right">{formatPercent(r.citationPrecision, 0)}</td>
                    <td className="figure px-4 py-3 text-right">{formatDuration(r.latencyP50Ms)}</td>
                    <td className="figure px-4 py-3 text-right">{formatUsd(r.usdPerQuestion)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            Refusals: {evals.refusalCorrect.correct} of {evals.refusalCorrect.total} unanswerable questions correctly declined
            {published ? "" : " (placeholder)"}. Cost is at paid rates even when a free tier covered it.
          </p>
        </div>
      </section>

      {/* Attribution */}
      <section id="attribution" aria-labelledby="attribution-title" className="scroll-mt-6 border-b border-border">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead mark="5 · sources" id="attribution-title" title="Built on open documentation." />
          <div className="mt-8 grid gap-5 md:grid-cols-2">
            <div className="rounded-lg border border-border bg-sheet p-5">
              <p className="font-semibold">Expo documentation</p>
              <p className="mt-2 text-sm leading-relaxed text-foreground/80">
                From the{" "}
                <a href={EXPO_REPO_URL} className={textLink}>
                  expo/expo
                </a>{" "}
                repository, © 650 Industries, Inc., under the{" "}
                <a href={EXPO_LICENSE_URL} className={textLink}>
                  MIT licence
                </a>
                . Passages are quoted with a link to the page on docs.expo.dev.
              </p>
            </div>
            <div className="rounded-lg border border-border bg-sheet p-5">
              <p className="font-semibold">React Native documentation</p>
              <p className="mt-2 text-sm leading-relaxed text-foreground/80">
                From{" "}
                <a href={RN_DOCS_REPO_URL} className={textLink}>
                  facebook/react-native-website
                </a>
                , © Meta Platforms, Inc. and affiliates, under{" "}
                <a href={CC_BY_URL} className={textLink}>
                  CC BY 4.0
                </a>
                . Passages are shown as retrieved, attributed and linked to reactnative.dev; answers are new text written from
                them.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" aria-labelledby="faq-title" className="scroll-mt-6">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead mark="6 · faq" id="faq-title" title="Questions" />
          <div className="mt-8">
            <Faq />
          </div>
          <div className="mt-14 flex flex-col items-start gap-4 rounded-lg border border-border bg-sheet p-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="font-serif text-xl font-semibold">Which SDK are you on?</p>
            <Link href={links.ask} className={ctaPrimary}>
              Ask the docs
              <ArrowRightIcon className="size-4" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
