"""Parse one docs page: frontmatter, then Markdown into heading-bounded sections of blocks.

    page.mdx --frontmatter--> {title, description, platforms, packageName, id}
             --reduce_mdx-->  Markdown
             --sections-->    [Section(heading_path=[title, "Usage", "Handle push..."],
                                       anchor="handle-push-notifications-with-navigation",
                                       blocks=[Block(prose), Block(code), Block(table)])]

Blocks are the unit the chunker packs. Three kinds, because each has a different rule:
prose may be split at sentence boundaries, a code block is never split, a table is kept
whole (a table row without its header row is a list of values with no meaning).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

from .mdx import FENCE_RE, ReduceContext, reduce_mdx, strip_frontmatter

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
CUSTOM_ID_RE = re.compile(r"\s*\{#([\w-]+)\}\s*$")
TABLE_LINE_RE = re.compile(r"^\s*\|")

BlockKind = Literal["prose", "code", "table"]


@dataclass
class Block:
    kind: BlockKind
    text: str


@dataclass
class Section:
    heading_path: list[str]  # [page title, h2, h3, ...]
    level: int  # 1 for the page intro (before the first heading)
    anchor: str | None
    blocks: list[Block] = field(default_factory=list)
    # The anchor of every heading in heading_path (None for the page title), so a chunk
    # that merges two sibling sections can link to their common parent.
    anchors: list[str | None] = field(default_factory=list)


@dataclass
class ParsedPage:
    path: str
    title: str
    description: str | None
    platforms: list[str]
    frontmatter: dict[str, Any]
    markdown: str
    sections: list[Section]


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


class Slugger:
    """GitHub-style heading slugs (what both Expo's and Docusaurus' sites generate):
    lowercase, drop punctuation, spaces to hyphens, de-duplicate with -1, -2."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    @staticmethod
    def base(text: str) -> str:
        text = re.sub(r"`([^`]*)`", r"\1", text)  # inline code keeps its text
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their label
        text = re.sub(r"[*_~]", "", text)
        text = unicodedata.normalize("NFKC", text).lower().strip()
        text = re.sub(r"[^\w\- ]", "", text)
        return text.replace(" ", "-")

    def slug(self, text: str) -> str:
        base = self.base(text)
        count = self.seen.get(base, 0)
        self.seen[base] = count + 1
        return base if count == 0 else f"{base}-{count}"


def heading_text(raw: str) -> str:
    """Display text of a heading: no Markdown emphasis, links reduced to their label."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    text = re.sub(r"\*\*|__", "", text)
    return " ".join(text.split())


def split_blocks(lines: list[str]) -> list[Block]:
    """Group a section's body lines into prose paragraphs, code blocks and tables."""
    blocks: list[Block] = []
    prose: list[str] = []
    i = 0

    def flush_prose() -> None:
        text = "\n".join(prose).strip()
        if text:
            blocks.append(Block("prose", text))
        prose.clear()

    while i < len(lines):
        line = lines[i]
        fence = FENCE_RE.match(line)
        if fence:
            flush_prose()
            marker = fence.group(2)
            code = [line]
            i += 1
            while i < len(lines):
                code.append(lines[i])
                closing = FENCE_RE.match(lines[i])
                i += 1
                if closing and closing.group(2).startswith(marker) and not closing.group(3).strip():
                    break
            blocks.append(Block("code", "\n".join(code).strip()))
            continue
        if TABLE_LINE_RE.match(line):
            flush_prose()
            table = []
            while i < len(lines) and TABLE_LINE_RE.match(lines[i]):
                table.append(lines[i].strip())
                i += 1
            blocks.append(Block("table", "\n".join(table)))
            continue
        if not line.strip():
            flush_prose()
        else:
            prose.append(line)
        i += 1
    flush_prose()
    return blocks


def sections_from_markdown(markdown: str, title: str) -> list[Section]:
    slugger = Slugger()
    sections: list[Section] = []
    stack: list[tuple[int, str, str]] = []  # (level, text, anchor) for h2..h6
    current = Section(heading_path=[title], level=1, anchor=None, anchors=[None])
    body: list[str] = []
    fence: str | None = None

    def close() -> None:
        current.blocks = split_blocks(body)
        if current.blocks:
            sections.append(current)

    for line in markdown.split("\n"):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            if fence is None:
                fence = fence_match.group(2)
            elif fence_match.group(2).startswith(fence) and not fence_match.group(3).strip():
                fence = None
        heading = HEADING_RE.match(line) if fence is None and not fence_match else None
        if heading:
            level = len(heading.group(1))
            raw = heading.group(2)
            custom = CUSTOM_ID_RE.search(raw)
            if custom:
                raw = raw[: custom.start()]
            text = heading_text(raw)
            if level == 1:  # an in-body H1 restates the page title
                if text and text != title:
                    body.append(f"**{text}**")
                continue
            close()
            body = []
            while stack and stack[-1][0] >= level:
                stack.pop()
            anchor = custom.group(1) if custom else slugger.slug(raw)
            if custom:
                slugger.seen[anchor] = slugger.seen.get(anchor, 0) + 1
            stack.append((level, text, anchor))
            current = Section(
                heading_path=[title, *(t for _, t, _ in stack)],
                level=level,
                anchor=anchor,
                anchors=[None, *(a for _, _, a in stack)],
            )
            continue
        body.append(line)
    close()
    return sections


def parse_page(
    path: str,
    raw: str,
    *,
    resolve_partial: Any = None,
) -> ParsedPage:
    frontmatter = parse_frontmatter(raw)
    body = strip_frontmatter(raw) if frontmatter or raw.startswith("---") else raw
    ctx = ReduceContext(
        package_name=frontmatter.get("packageName"),
        resolve_partial=resolve_partial,
    )
    markdown = reduce_mdx(body, ctx)
    title = str(frontmatter.get("title") or "").strip()
    if not title:
        first_h1 = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        title = heading_text(first_h1.group(1)) if first_h1 else path.rsplit("/", 1)[-1]
    platforms = frontmatter.get("platforms") or []
    if isinstance(platforms, str):
        platforms = [platforms]
    description = frontmatter.get("description")
    return ParsedPage(
        path=path,
        title=title,
        description=str(description).strip() if description else None,
        platforms=[str(p) for p in platforms],
        frontmatter=frontmatter,
        markdown=markdown,
        # The frontmatter description opens the intro section: it is the page's own
        # one-line summary and often the best match for "what is X" questions.
        sections=sections_from_markdown(
            (f"{description}\n\n" if description else "") + markdown, title
        ),
    )
