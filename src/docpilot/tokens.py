"""Token counting with tiktoken `o200k_base`, degrading to a 4-chars-per-token estimate.

Counts are used to size chunks and to keep the answer prompt under Groq's 8K tokens-per-
minute free-tier limit. `o200k_base` is the gpt-oss tokenizer family; Gemini and the
embedding models tokenize differently, so every count here is an approximation that is
good enough for budgets. What the ledger records afterwards is the provider's own usage.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...


class ApproxCounter:
    """~4 characters per token. The offline fallback, and the deterministic test double."""

    name = "approx-4cpt"

    def count(self, text: str) -> int:
        return math.ceil(len(text) / 4)


class TiktokenCounter:
    name = "tiktoken:o200k_base"

    def __init__(self) -> None:
        import tiktoken

        self._encoding = tiktoken.get_encoding("o200k_base")

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


@lru_cache(maxsize=1)
def default_counter() -> TokenCounter:
    try:
        return TiktokenCounter()
    except Exception as exc:  # offline, no cached encoding file
        log.warning("tiktoken unavailable (%s); using the 4-chars-per-token estimate", exc)
        return ApproxCounter()
