import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";
import { ArrowLeftIcon, CircleSlashIcon } from "lucide-react";
import { AnswerDocument } from "@/components/answer/answer-document";
import { FeedbackButtons } from "@/components/ask/feedback-buttons";
import { ShareLink } from "@/components/ask/share-link";
import { getQuestion, type StoredQuestion } from "@/lib/api";
import { ApiError, errorTitle } from "@/lib/errors";
import { container, ctaSecondary } from "@/lib/site";
import { storedToView } from "@/lib/turn";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

type Loaded = { ok: true; q: StoredQuestion } | { ok: false; error: ApiError };

/** One fetch per request, shared by generateMetadata and the page. */
const load = cache(async (id: string): Promise<Loaded> => {
  try {
    return { ok: true, q: await getQuestion(id) };
  } catch (e) {
    return {
      ok: false,
      error: e instanceof ApiError ? e : new ApiError({ status: 500, code: "server", message: "Could not load this question." }),
    };
  }
});

export async function generateMetadata({ params }: PageProps<"/q/[id]">): Promise<Metadata> {
  const { id } = await params;
  const r = await load(id);
  const title = r.ok ? r.q.question.slice(0, 90) : "Stored question";
  return { title, robots: { index: false, follow: false } };
}

export default async function QuestionPage({ params }: PageProps<"/q/[id]">) {
  const { id } = await params;
  const r = await load(id);

  if (!r.ok) {
    if (r.error.code === "question_not_found" || r.error.status === 404) notFound();
    return (
      <div className={cn(container, "py-16")}>
        <p className="kicker">§ stored answer</p>
        <h1 className="mt-2 font-serif text-3xl font-semibold">{errorTitle(r.error)}</h1>
        <p role="alert" className="mt-3 flex max-w-xl items-start gap-2 text-foreground/85">
          <CircleSlashIcon className="mt-1 size-4 shrink-0 text-destructive" aria-hidden="true" />
          {r.error.message}
        </p>
        <Link href="/ask" className={cn(ctaSecondary, "mt-8")}>
          Ask a new question
        </Link>
      </div>
    );
  }

  const view = storedToView(r.q);
  return (
    <div className={cn(container, "py-8 sm:py-12")}>
      <nav aria-label="Breadcrumb" className="mb-6">
        <Link href="/ask" className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeftIcon className="size-3.5" aria-hidden="true" />
          Ask your own question
        </Link>
      </nav>
      <AnswerDocument
        view={view}
        idPrefix="q"
        headingLevel={1}
        actions={
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <ShareLink questionId={r.q.id} />
            <FeedbackButtons questionId={r.q.id} initial={r.q.feedback} />
          </div>
        }
      />
      <p className="mt-10 max-w-2xl text-xs text-muted-foreground">
        A stored answer: the question, the passages it was answered from and the verifier&apos;s result, exactly as they were
        when it was asked. The docs may have changed since.
      </p>
    </div>
  );
}
