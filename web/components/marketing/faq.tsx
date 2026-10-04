import { links, textLink } from "@/lib/site";

const items: { q: string; a: React.ReactNode }[] = [
  {
    q: "Which docs does it answer from?",
    a: (
      <p>
        The latest two Expo SDK versions plus Expo&apos;s unversioned guides (EAS, Router and the rest), and the current React
        Native docs. Each answer searches only the version you picked, together with the guides that apply to every version.
      </p>
    ),
  },
  {
    q: "What does “verified” mean on a citation?",
    a: (
      <p>
        After the model finishes, plain code checks every <code className="figure text-[0.9em]">[n]</code> against the passages
        that were actually retrieved, and checks any quoted fragment against that passage&apos;s text. A citation that fails is
        removed from the answer and listed, struck through, in the source panel. An answer left with no supporting passage is
        labelled unsupported instead of being dressed up.
      </p>
    ),
  },
  {
    q: "Why does the version matter so much?",
    a: (
      <p>
        Because Expo changes every SDK release: options get renamed, defaults move, features leave Expo Go. An answer written
        for SDK 52 can be wrong on SDK 53. DocPilot never mixes versions in one answer unless you ask it to compare them.
      </p>
    ),
  },
  {
    q: "Is my question stored?",
    a: (
      <p>
        Yes: the question, the retrieved passages, the answer and its usage are stored so the answer has a shareable link and
        so retrieval can be measured. There are no accounts and no cookies. The thread of follow-ups lives in your browser tab;
        only its last few turns are sent with the next question, to rewrite it into a standalone search.
      </p>
    ),
  },
  {
    q: "Which models does it use?",
    a: (
      <p>
        One embedding model per corpus (Voyage or Gemini, chosen at ingest), a reranker when available, and an open-weight
        model on Groq for the answer with Gemini as a fallback. Every answer shows its tokens and what it would cost at paid
        rates.
      </p>
    ),
  },
  {
    q: "Is this an official Expo or Meta project?",
    a: (
      <p>
        No. It is an independent learning project in the{" "}
        <a href={links.journey} className={textLink}>
          AI Engineering Journey
        </a>
        , built on the docs&apos; open licences. For anything that matters, follow the citation and read the page.
      </p>
    ),
  },
];

export function Faq() {
  return (
    <div className="divide-y divide-border border-y border-border">
      {items.map((it) => (
        <details key={it.q} className="group py-1">
          <summary className="flex cursor-pointer list-none items-start justify-between gap-4 rounded-sm py-3.5 font-medium [&::-webkit-details-marker]:hidden">
            <span>{it.q}</span>
            <span aria-hidden="true" className="figure text-muted-foreground group-open:rotate-45 motion-safe:transition-transform">
              +
            </span>
          </summary>
          <div className="max-w-2xl pb-4 text-[0.9375rem] leading-relaxed text-foreground/80">{it.a}</div>
        </details>
      ))}
    </div>
  );
}
