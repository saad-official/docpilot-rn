# 0004 — Deterministic citation verification before an answer is shown as supported

Date: 2026-10-05. Status: accepted.

## Context

A RAG answer with numbered citations looks trustworthy whether or not the numbers mean
anything. Models cite passages they were never given ([9] when there were eight), attach
a correct-looking citation to a claim from prior knowledge, and put words in quotation
marks that appear in no passage. For version-sensitive docs the last one is the dangerous
one: a quote from SDK 52's docs, attributed to an SDK 58 passage.

## Decision (`src/docpilot/answer/verify.py`)

After the stream ends, before the `citations` event:

1. **Mapping.** Every `[n]` (also `[1, 3]`) outside code spans must be a passage number
   that was in the prompt. Others are removed from the rendered answer and listed in
   `removed` with a reason.
2. **Quotes.** Every quoted fragment of six or more words (`"..."` or `“...”`) must appear,
   after normalisation (case, whitespace, curly quotes, Markdown emphasis, punctuation), in
   one of the passages cited *in the same sentence*. If none contains it, that sentence's
   citations are removed (`quoted text not found in this passage`).
3. **Labels.** No verified citation left: `unsupported` (the UI shows a warning, not a
   confident answer). Some removed: `partial`. Otherwise `supported`. A refusal (the answer
   opens with the exact "I couldn't find this in the … docs" sentence the prompt requires)
   is flagged `refused`.
4. Each verified citation carries a `quote` that is verbatim passage text: the model's own
   quote when it had one, otherwise the passage sentence with the most word overlap with
   the citing sentence, so the source panel can highlight it.

The streamed tokens are shown live (latency matters), and the final `answer` in the
`citations` event replaces them with the verified rendering.

## What it does not do

It does not prove that a paraphrase is entailed by its passage. That needs a model and is
probabilistic; the eval's optional LLM judge (`--judge`) measures faithfulness on the
golden set instead of paying for a second model call on every question. Cheap, certain
checks on every answer; expensive, probabilistic ones on the test set.

## Diff mode

The structured `DiffAnswer` is cleaned first (citation numbers that name no passage are
dropped; a change left with none is removed and counted in `dropped_changes`), the prose
is rendered from it by code, and the same verifier runs on that prose.

## Consequences

- Citation precision (verified / emitted) becomes a metric in `docs/evals.md`, and a drop
  in it is a regression signal for prompt or model changes.
- A model that cites nothing is labelled `unsupported` even when it is right. That is the
  intended bias for a docs tool: an unsupported answer should look unsupported.
