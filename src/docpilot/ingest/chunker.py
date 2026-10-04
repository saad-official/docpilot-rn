"""Structure-aware chunking: heading-bounded, 400-700 tokens, code and tables never split.

Rules, in the order they are applied (docs/decisions/0002-chunking.md has the why):

  1. A heading starts a new section. A chunk never spans two pages.
  2. Within a section, blocks are packed greedily up to MAX_TOKENS (700).
     - A code block or table is atomic. One larger than MAX_TOKENS becomes a chunk of its
       own, with its heading context, rather than being cut in half: half a code sample
       is worse than an oversized chunk.
     - A prose block larger than MAX_TOKENS is split at sentence boundaries.
  3. Continuation chunks (the 2nd, 3rd... piece of one section) start with the section's
     heading and its first sentence: the "heading sentence" overlap. It costs a few tokens
     and means every chunk says what it is about.
  4. Small neighbours are merged: while a chunk is under MIN_TOKENS (400) and the next
     piece fits under MAX_TOKENS and shares the same H2, they become one chunk whose
     heading path is their common parent. Expo pages are full of 60-token H3 sections; on
     their own they embed poorly and crowd the top-k with fragments.

Counting uses tiktoken `o200k_base` (tokens.py).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..models import HEADING_SEP, Chunk, ChunkKind, Sdk
from ..tokens import TokenCounter, default_counter
from .parse import Block, ParsedPage, Section

MIN_TOKENS = 400
MAX_TOKENS = 700

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`*\[(])|\n(?=\s*(?:[-*+]|\d+\.)\s)")


@dataclass
class Piece:
    heading_path: list[str]
    anchors: list[str | None]
    level: int
    texts: list[str] = field(default_factory=list)
    kinds: set[str] = field(default_factory=set)
    tokens: int = 0

    @property
    def kind(self) -> ChunkKind:
        if self.kinds == {"code"}:
            return "code"
        if self.kinds == {"table"}:
            return "table"
        return "prose"

    @property
    def text(self) -> str:
        return "\n\n".join(self.texts)


def heading_line(section: Section) -> str | None:
    if section.level <= 1:
        return None
    return f"{'#' * section.level} {section.heading_path[-1]}"


LABEL_LINE_RE = re.compile(r"^\*\*[^*\n]{1,80}:?\*\*:?$")


def first_sentence(section: Section) -> str | None:
    """The section's opening sentence (skipping tab labels and fragments under 4 words)."""
    for block in section.blocks:
        if block.kind != "prose":
            continue
        for line in block.text.strip().split("\n"):
            line = line.strip()
            if not line or LABEL_LINE_RE.match(line) or len(line.split()) < 4:
                continue
            sentence = SENTENCE_RE.split(line, maxsplit=1)[0].strip()
            return sentence[:300]
    return None


def split_prose(text: str, limit: int, counter: TokenCounter) -> list[str]:
    """Split an oversized paragraph at sentence (or list-item) boundaries."""
    parts = [p for p in SENTENCE_RE.split(text) if p.strip()]
    out: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current} {part}".strip() if current else part
        if current and counter.count(candidate) > limit:
            out.append(current)
            current = part
        else:
            current = candidate
    if current:
        out.append(current)
    # A single sentence longer than the limit is cut on whitespace as a last resort.
    final: list[str] = []
    for piece in out:
        if counter.count(piece) <= limit:
            final.append(piece)
            continue
        words, buf = piece.split(" "), ""
        for word in words:
            candidate = f"{buf} {word}".strip()
            if buf and counter.count(candidate) > limit:
                final.append(buf)
                buf = word
            else:
                buf = candidate
        if buf:
            final.append(buf)
    return final


def section_pieces(
    section: Section, counter: TokenCounter, max_tokens: int = MAX_TOKENS
) -> list[Piece]:
    """Pack one section's blocks into pieces of at most `max_tokens` (atomic blocks aside)."""
    header = heading_line(section)
    lead = first_sentence(section)
    pieces: list[Piece] = []

    def new_piece(continuation: bool) -> Piece:
        piece = Piece(list(section.heading_path), list(section.anchors), section.level)
        prefix = [header] if header else []
        if continuation and lead:
            prefix.append(f"(continued) {lead}")
        if prefix:
            text = "\n\n".join(prefix)
            piece.texts.append(text)
            piece.tokens = counter.count(text)
        return piece

    current = new_piece(continuation=False)
    has_body = False

    def add(block_text: str, kind: str) -> None:
        nonlocal current, has_body
        size = counter.count(block_text)
        # An atomic block that will be oversized anyway absorbs a short lead-in paragraph
        # ("Check out the example below") instead of leaving it as a 50-token fragment.
        absorbs = kind != "prose" and size > max_tokens and current.tokens < max_tokens // 4
        if has_body and current.tokens + size > max_tokens and not absorbs:
            pieces.append(current)
            current = new_piece(continuation=True)
            has_body = False
        current.texts.append(block_text)
        current.kinds.add(kind)
        current.tokens += size
        has_body = True

    for block in section.blocks:
        size = counter.count(block.text)
        if block.kind == "prose" and size > max_tokens - current.tokens and size > max_tokens // 2:
            for part in split_prose(block.text, max_tokens // 2, counter):
                add(part, "prose")
        else:
            add(block.text, block.kind)
    if has_body:
        pieces.append(current)
    return pieces


def _common_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def merge_small(
    pieces: list[Piece], min_tokens: int = MIN_TOKENS, max_tokens: int = MAX_TOKENS
) -> list[Piece]:
    merged: list[Piece] = []
    for piece in pieces:
        if merged:
            last = merged[-1]
            # Same H2, or the page intro (which may absorb the first section after it).
            same_h2 = len(last.heading_path) == 1 or (
                len(last.heading_path) >= 2 and last.heading_path[:2] == piece.heading_path[:2]
            )
            if same_h2 and last.tokens < min_tokens and last.tokens + piece.tokens <= max_tokens:
                common = _common_prefix(last.heading_path, piece.heading_path)
                last.heading_path = last.heading_path[:common]
                last.anchors = last.anchors[:common]
                last.level = min(last.level, piece.level)
                last.texts.extend(piece.texts)
                last.kinds |= piece.kinds or {"prose"}
                last.tokens += piece.tokens
                continue
        merged.append(piece)
    return merged


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_id(sdk: str, version: str, path: str) -> str:
    return hashlib.sha1(f"{sdk}:{version}:{path}".encode()).hexdigest()[:20]


def chunk_page(
    page: ParsedPage,
    *,
    sdk: Sdk,
    version: str,
    url: str,
    counter: TokenCounter | None = None,
    min_tokens: int = MIN_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[Chunk]:
    """All chunks of one page. `url` is the page URL without an anchor."""
    counter = counter or default_counter()
    pieces: list[Piece] = []
    for section in page.sections:
        pieces.extend(section_pieces(section, counter, max_tokens))
    pieces = merge_small(pieces, min_tokens, max_tokens)

    doc_id = document_id(sdk, version, page.path)
    chunks: list[Chunk] = []
    seen_ids: set[str] = set()
    for ordinal, piece in enumerate(pieces):
        content = piece.text.strip()
        if not content:
            continue
        anchor = next((a for a in reversed(piece.anchors) if a), None)
        heading_path = HEADING_SEP.join(piece.heading_path)
        embed_text = f"{page.title}\n{heading_path}\n\n{content}"
        content_hash = sha256(embed_text)
        chunk_id = hashlib.sha1(f"{doc_id}:{anchor}:{content_hash}".encode()).hexdigest()[:24]
        if chunk_id in seen_ids:  # identical text twice on one page
            chunk_id = hashlib.sha1(f"{chunk_id}:{ordinal}".encode()).hexdigest()[:24]
        seen_ids.add(chunk_id)
        chunks.append(
            Chunk(
                id=chunk_id,
                document_id=doc_id,
                sdk=sdk,
                version=version,
                ordinal=ordinal,
                title=page.title,
                heading_path=heading_path,
                anchor=anchor,
                url=f"{url}#{anchor}" if anchor else url,
                kind=piece.kind,
                content=content,
                tokens=counter.count(content),
                content_hash=content_hash,
            )
        )
    return chunks


def blocks_text(blocks: list[Block]) -> str:
    return "\n\n".join(block.text for block in blocks)
