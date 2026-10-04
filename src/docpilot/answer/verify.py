"""The citation verifier: deterministic checks on every `[n]` before the user sees it.

    1. Mapping. `[n]` must name a passage that was actually in the prompt (1..N). A model
       that writes [9] when it saw eight passages cited nothing; the marker is removed.
    2. Quotes. A quoted fragment of six words or more ("..." or “...”) must appear in one
       of the passages cited in the same sentence, after normalisation (case, whitespace,
       curly quotes, Markdown emphasis, punctuation). If it appears in none of them, the
       sentence's citations are removed: the model attributed words to a source that does
       not contain them.
    3. Labelling. An answer left with no verified citation is `unsupported` (the UI shows
       a warning instead of a confident answer); one that lost some is `partial`.

What this does *not* prove: that a paraphrased sentence is entailed by its passage. That
needs a model (the eval's LLM judge measures it); the cheap, certain checks run on every
answer, the expensive, probabilistic one runs on the golden set. Decision record:
docs/decisions/0004-citation-verification.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from ..retrieval.context import Passage

CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[,;]\s*\d{1,3})*)\]")
QUOTE_RE = re.compile(r"\"([^\"\n]{8,}?)\"|“([^”\n]{8,}?)”")
FENCE_RE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# Sentence ends: . ! ? followed by space, unless a citation follows ("... works. [2]"
# keeps [2] with the sentence it closes); and line breaks.
SEGMENT_RE = re.compile(r"(?<=[.!?])\s+(?!\[\d)|\n+")
MIN_QUOTE_WORDS = 6
REFUSAL_PREFIXES = ("i couldn't find this", "i could not find this", "i couldn’t find this")

Status = Literal["supported", "partial", "unsupported"]


class VerifiedCitation(BaseModel):
    n: int
    chunk_id: str
    url: str
    title: str
    heading_path: str
    version: str
    # Verbatim text from the passage: the quote the answer used, or the passage sentence
    # that best matches the citing sentence (for highlighting in the source panel).
    quote: str | None = None
    quote_source: Literal["answer", "overlap"] | None = None


class RemovedCitation(BaseModel):
    n: int
    reason: str


class Verification(BaseModel):
    status: Status
    unsupported: bool
    refused: bool
    emitted: int = Field(description="citation markers the model wrote")
    verified: int = Field(description="markers kept")
    removed: int
    precision: float | None = Field(description="verified / emitted; None when nothing cited")
    quotes_checked: int = 0
    quotes_verified: int = 0
    uncited_quotes: int = 0


class VerifiedAnswer(BaseModel):
    answer: str
    verified: list[VerifiedCitation]
    removed: list[RemovedCitation]
    verification: Verification

    def citations_payload(self) -> dict:
        """The `citations` object the web app reads: {verified, removed, unsupported}."""
        return {
            "verified": [c.model_dump() for c in self.verified],
            "removed": [c.model_dump() for c in self.removed],
            "unsupported": self.verification.unsupported,
        }


def normalise(text: str) -> str:
    text = text.lower()
    text = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "`": " "}))
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _protected(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in FENCE_RE.finditer(text)]
    spans += [m.span() for m in INLINE_CODE_RE.finditer(text)]
    return spans


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _segments(text: str) -> list[tuple[int, int]]:
    bounds: list[tuple[int, int]] = []
    start = 0
    for match in SEGMENT_RE.finditer(text):
        bounds.append((start, match.start()))
        start = match.end()
    bounds.append((start, len(text)))
    return bounds


_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_COMMON = frozenset("the and for you your with that this from are can use not but its".split())  # noqa: SIM905


def best_sentence(content: str, claim: str) -> str | None:
    """The passage sentence (verbatim) sharing the most content words with the claim."""
    claim_words = {w for w in _WORD_RE.findall(claim.lower()) if w not in _COMMON}
    if not claim_words:
        return None
    best: tuple[int, str] | None = None
    in_code = False
    for line in content.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.strip() or line.lstrip().startswith(("#", "|")):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
            words = {w for w in _WORD_RE.findall(sentence.lower()) if w not in _COMMON}
            overlap = len(words & claim_words)
            if overlap >= 2 and (best is None or overlap > best[0]):
                best = (overlap, sentence.strip()[:300])
    return best[1] if best else None


def is_refusal(text: str) -> bool:
    head = text.lstrip().lstrip("*_> ").lower()
    return head.startswith(REFUSAL_PREFIXES)


def verify_answer(text: str, passages: Sequence[Passage]) -> VerifiedAnswer:
    by_n = {p.n: p for p in passages}
    normalised = {p.n: normalise(p.chunk.content) for p in passages}
    protected = _protected(text)

    groups = [m for m in CITE_RE.finditer(text) if not _inside(m.start(), protected)]
    removed: list[RemovedCitation] = []
    keep: dict[int, list[int]] = {}  # group start -> kept numbers
    emitted = 0
    quote_for: dict[int, str] = {}  # n -> verified quote
    quotes_checked = quotes_verified = uncited_quotes = 0

    for seg_start, seg_end in _segments(text):
        seg_groups = [g for g in groups if seg_start <= g.start() < seg_end]
        numbers = [
            (g, int(n)) for g in seg_groups for n in re.split(r"\s*[,;]\s*", g.group(1)) if n
        ]
        emitted += len(numbers)
        valid = [(g, n) for g, n in numbers if n in by_n]
        for _, n in numbers:
            if n not in by_n:
                removed.append(RemovedCitation(n=n, reason="no passage with this number"))
        segment = text[seg_start:seg_end]
        quotes = [
            q
            for m in QUOTE_RE.finditer(segment)
            if not _inside(seg_start + m.start(), protected)
            for q in [m.group(1) or m.group(2)]
            if len(q.split()) >= MIN_QUOTE_WORDS
        ]
        failed_quote = False
        for quote in quotes:
            if not valid:
                uncited_quotes += 1
                continue
            quotes_checked += 1
            needle = normalise(quote)
            hits = [n for _, n in valid if needle and needle in normalised[n]]
            if hits:
                quotes_verified += 1
                for n in hits:
                    quote_for.setdefault(n, quote.strip())
            else:
                failed_quote = True
        for group, n in valid:
            if failed_quote:
                removed.append(RemovedCitation(n=n, reason="quoted text not found in this passage"))
            else:
                keep.setdefault(group.start(), []).append(n)

    # Rebuild the text with only the kept markers, normalised to [a][b] form.
    out: list[str] = []
    last = 0
    for group in groups:
        kept = list(dict.fromkeys(keep.get(group.start(), [])))
        prefix = text[last : group.start()]
        if not kept:
            prefix = prefix.rstrip(" ")
        out.append(prefix)
        out.append("".join(f"[{n}]" for n in kept))
        last = group.end()
    out.append(text[last:])
    rendered = "".join(out)
    rendered = re.sub(r"[ \t]+([.,;:!?])", r"\1", rendered)

    verified: list[VerifiedCitation] = []
    seen: set[int] = set()
    segments = _segments(text)
    for group in groups:
        for n in keep.get(group.start(), []):
            if n in seen:
                continue
            seen.add(n)
            chunk = by_n[n].chunk
            quote, source = quote_for.get(n), "answer"
            if quote is None:
                seg = next(
                    text[s:e] for s, e in segments if s <= group.start() < e or e == len(text)
                )
                quote, source = best_sentence(chunk.content, CITE_RE.sub("", seg)), "overlap"
            verified.append(
                VerifiedCitation(
                    n=n,
                    chunk_id=chunk.id,
                    url=chunk.url,
                    title=chunk.title,
                    heading_path=chunk.heading_path,
                    version=chunk.version,
                    quote=quote,
                    quote_source=source if quote else None,
                )
            )

    n_verified = sum(len(v) for v in keep.values())
    if not verified:
        status: Status = "unsupported"
    elif removed:
        status = "partial"
    else:
        status = "supported"
    return VerifiedAnswer(
        answer=rendered.strip(),
        verified=verified,
        removed=removed,
        verification=Verification(
            status=status,
            unsupported=status == "unsupported",
            refused=is_refusal(text),
            emitted=emitted,
            verified=n_verified,
            removed=len(removed),
            precision=(n_verified / emitted) if emitted else None,
            quotes_checked=quotes_checked,
            quotes_verified=quotes_verified,
            uncited_quotes=uncited_quotes,
        ),
    )
