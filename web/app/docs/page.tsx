import type { Metadata } from "next";
import Link from "next/link";
import { CodeBlock } from "@/components/code-block";
import { API_URL } from "@/lib/config";
import { container, links, textLink } from "@/lib/site";
import { curlAsk, curlDiff, curlQuestion, curlVersions, evalCommands, ingestCommands, streamExample } from "@/lib/snippets";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Docs",
  description: "How to use DocPilot RN, the HTTP API with curl examples, how the corpus is built and how to run ingestion.",
};

const toc = [
  { id: "use", label: "Using it" },
  { id: "api", label: "HTTP API" },
  { id: "corpus", label: "The corpus" },
  { id: "ingest", label: "Running ingestion" },
];

const h2 = "font-serif text-2xl font-semibold sm:text-3xl";
const p = "max-w-2xl leading-relaxed text-foreground/80";
const code = "figure text-[0.9em]";

export default function DocsPage() {
  const api = API_URL;
  return (
    <div className={cn(container, "py-10 sm:py-14")}>
      <div className="grid gap-10 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-14">
        <nav aria-label="On this page" className="lg:sticky lg:top-8 lg:h-fit">
          <p className="kicker">§ docs</p>
          <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm lg:flex-col lg:gap-2.5">
            {toc.map((t) => (
              <li key={t.id}>
                <a href={`#${t.id}`} className={textLink}>
                  {t.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-16">
          <header className="max-w-2xl space-y-3">
            <h1 className="font-serif text-4xl font-semibold sm:text-5xl">Docs</h1>
            <p className="text-[1.0625rem] leading-relaxed text-foreground/80">
              The web app is one client of a small HTTP API. Everything it does, you can do with curl. The full reference is in
              the{" "}
              <a href={links.repo} className={textLink}>
                repository README
              </a>
              .
            </p>
          </header>

          <section id="use" aria-labelledby="use-title" className="scroll-mt-8 space-y-4">
            <h2 id="use-title" className={h2}>
              Using it
            </h2>
            <ol className="max-w-2xl list-decimal space-y-2.5 pl-5 leading-relaxed text-foreground/85 marker:text-muted-foreground">
              <li>
                On{" "}
                <Link href={links.ask} className={textLink}>
                  /ask
                </Link>
                , pick the source (Expo or React Native) and the version you are on. The newest indexed version is selected by
                default.
              </li>
              <li>
                Ask in plain words. Name the API if you know it (<code className={code}>expo-notifications</code>,{" "}
                <code className={code}>useRouter</code>): exact names are boosted in retrieval.
              </li>
              <li>
                The sources appear first, then the answer streams in. Numbered chips link to the passage in the panel; once the
                verifier has run, cited passages show the quoted sentence highlighted, and any citation it removed is listed,
                struck through, with the reason.
              </li>
              <li>
                Switch to <strong className="font-semibold">What changed?</strong> and pick a second version to get a structured
                diff (added, removed, renamed, behaviour) with citations to each version, above the explanation.
              </li>
              <li>
                Follow-ups use the last four turns of this tab&apos;s thread to rewrite the question; start a new thread to drop
                them. Every finished answer has a permanent link at <code className={code}>/q/&lt;id&gt;</code>.
              </li>
            </ol>
            <p className={p}>
              Limits: 30 questions per hour per IP address, questions up to 1,000 characters. The answer is grounded in the docs
              only; if the passages do not cover the question it says so and names the page to read.
            </p>
          </section>

          <section id="api" aria-labelledby="api-title" className="scroll-mt-8 space-y-5">
            <h2 id="api-title" className={h2}>
              HTTP API
            </h2>
            <p className={p}>
              Base URL <code className={code}>{api}</code>. JSON in and out, except <code className={code}>/api/ask</code>, which
              answers with Server-Sent Events. Because it is a POST, browsers read it with{" "}
              <code className={code}>fetch</code> and a stream reader rather than <code className={code}>EventSource</code>.
            </p>
            <CodeBlock label="list indexed versions" code={curlVersions(api)} />
            <CodeBlock label="ask (stream)" code={curlAsk(api)} />
            <p className={p}>
              Events arrive in this order: <code className={code}>retrieval</code>, many <code className={code}>token</code>s,{" "}
              <code className={code}>citations</code>, then <code className={code}>done</code> (or{" "}
              <code className={code}>error</code> at any point). In diff mode a <code className={code}>diff</code> event carries
              the structured comparison.
            </p>
            <CodeBlock label="stream (abridged)" code={streamExample} />
            <CodeBlock label="what changed?" code={curlDiff(api)} />
            <CodeBlock label="stored answers and feedback" code={curlQuestion(api)} />
            <p className={p}>
              Errors before the stream starts are JSON:{" "}
              <code className={code}>{`{ "detail": { "code", "message", "retry_after"? } }`}</code> with 429{" "}
              <code className={code}>rate_limited</code>, 400 <code className={code}>invalid_input</code>, 404{" "}
              <code className={code}>version_not_found</code> or 503 <code className={code}>unavailable</code>.{" "}
              <code className={code}>GET /api/health</code> reports the database, corpus freshness and providers; this site
              proxies it at{" "}
              <a href="/api/health" className={textLink}>
                /api/health
              </a>
              .
            </p>
          </section>

          <section id="corpus" aria-labelledby="corpus-title" className="scroll-mt-8 space-y-4">
            <h2 id="corpus-title" className={h2}>
              The corpus
            </h2>
            <ul className="max-w-2xl list-disc space-y-2.5 pl-5 leading-relaxed text-foreground/85 marker:text-muted-foreground">
              <li>
                <strong className="font-semibold">Expo</strong>: the latest two SDK versions under{" "}
                <code className={code}>docs/pages/versions/</code> plus the unversioned guides (
                <code className={code}>guides</code>, <code className={code}>eas</code>, <code className={code}>router</code>
                , and so on, without translations), from <code className={code}>expo/expo</code> (MIT).
              </li>
              <li>
                <strong className="font-semibold">React Native</strong>: the current docs from{" "}
                <code className={code}>facebook/react-native-website</code> (CC BY 4.0), one version.
              </li>
              <li>
                MDX is parsed with its frontmatter; headings are the chunk boundary (400 to 700 tokens of prose); code blocks
                and tables are never split; Expo components such as <code className={code}>&lt;APISection&gt;</code> and{" "}
                <code className={code}>&lt;Terminal&gt;</code> are reduced to their text. Each chunk keeps its heading path and
                a URL with the anchor, which is what the citation links to.
              </li>
              <li>
                One embedding model per corpus; the model and its dimension are stored with the corpus, and switching means
                re-embedding. Retrieval is hybrid (pgvector and Postgres full text, fused with RRF), then reranked.
              </li>
            </ul>
          </section>

          <section id="ingest" aria-labelledby="ingest-title" className="scroll-mt-8 space-y-4">
            <h2 id="ingest-title" className={h2}>
              Running ingestion
            </h2>
            <p className={p}>
              Ingestion is a command-line job, run locally or from a manually triggered GitHub Actions workflow with the
              database URL as a secret. It is never exposed over HTTP.
            </p>
            <CodeBlock label="ingest" code={ingestCommands} />
            <p className={p}>
              The evaluation harness scores retrieval and citations against the golden set and writes the report the landing
              page links to.
            </p>
            <CodeBlock label="evals" code={evalCommands} />
          </section>
        </div>
      </div>
    </div>
  );
}
