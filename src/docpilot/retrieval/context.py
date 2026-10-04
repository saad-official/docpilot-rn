"""Context assembly: the retrieved chunks the model sees, numbered [1]..[n], under a budget.

Each passage is wrapped in a tag that carries its id, version, title and URL. The
content is escaped so a docs page containing "</passage>" cannot close our delimiter and
start talking to the model as if it were the system prompt (prompt injection through
retrieved text is the RAG-specific version of that attack).

Budget: ~6,000 tokens of passages. Groq's free tier allows 8,000 tokens per minute per
model; passages + system prompt + question + up to ~1,500 output tokens must fit one
minute, or the request is rejected outright (413) rather than slowed down.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from ..models import RetrievedChunk
from ..tokens import TokenCounter, default_counter

TOP_N = 8


class Passage(BaseModel):
    n: int
    chunk: RetrievedChunk


def escape(text: str) -> str:
    return text.replace("</passage", "&lt;/passage").replace("<passage", "&lt;passage")


def passage_xml(passage: Passage, version_label: str | None = None) -> str:
    chunk = passage.chunk
    version = version_label or chunk.version
    return (
        f'<passage id="{passage.n}" version="{version}" title="{escape(chunk.title)}" '
        f'section="{escape(chunk.heading_path)}" url="{chunk.url}">\n'
        f"{escape(chunk.content)}\n</passage>"
    )


def assemble(
    chunks: Sequence[RetrievedChunk],
    *,
    budget_tokens: int = 6000,
    top_n: int = TOP_N,
    counter: TokenCounter | None = None,
    start: int = 1,
) -> list[Passage]:
    """Take chunks in order until `top_n` or the budget is reached.

    A chunk that does not fit is skipped (a smaller one further down may still fit), but
    the first chunk is always included: an answer from one long passage beats no answer.
    """
    counter = counter or default_counter()
    passages: list[Passage] = []
    used = 0
    for chunk in chunks:
        if len(passages) >= top_n:
            break
        size = counter.count(chunk.content) + 40  # + the tag line
        if passages and used + size > budget_tokens:
            continue
        passages.append(Passage(n=start + len(passages), chunk=chunk))
        used += size
    return passages


def render_passages(passages: Sequence[Passage]) -> str:
    return "<passages>\n" + "\n\n".join(passage_xml(p) for p in passages) + "\n</passages>"
