"""The project's thin adapter over llm-kit: fallback routes, quota cooldowns, TPM pacing.

Copied from Changelog Forge's adapter and adapted for an interactive product (llm-kit
knows about providers, projects know about problems):

  1. Fallback across providers. When Groq is rate-limited, a model id is withdrawn, or
     output will not validate, the same call is re-issued on the next route in
     `routing.toml`. A budget error is never a reason to fall back.
  2. Quota cooldown. A daily-quota 429 ("per day (TPD)") parks the route until its reset;
     a per-minute 429 parks it for its Retry-After. Later questions skip it immediately
     instead of paying a retry deadline each time.
  3. Tokens-per-minute pacing. Groq's free tier caps tokens per minute (8,000). A batch job
     sleeps until the window has room; an interactive question does not wait more than
     `max_wait_s` - it takes the fallback ("fall back to Gemini when Groq is cooling down").
  4. Streaming with fallback *before the first token*. llm-kit's `stream()` raises the
     SDK's exception from the request itself; until a token has been yielded nothing has
     reached the user, so the next route can take over invisibly. After the first token a
     failure is reported, not hidden.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from typing import Any, Protocol, TypeVar

from llm_kit import (
    LLM,
    CallRecord,
    Ledger,
    LLMBudgetError,
    LLMError,
    LLMOutputError,
    LLMPermanentError,
    LLMTransientError,
    RetryPolicy,
    Usage,
    classify,
)
from llm_kit import Settings as LLMSettings
from pydantic import BaseModel

from .routing import Route, Tier
from .tokens import TokenCounter, default_counter

TModel = TypeVar("TModel", bound=BaseModel)

WINDOW_S = 60.0


def is_schema_rejection(exc: Exception) -> bool:
    """Groq answers off-schema output with a 400; a resample usually succeeds."""
    text = str(exc)
    return isinstance(exc, LLMPermanentError) and (
        "does not match the expected schema" in text or "json_validate_failed" in text
    )


_DAILY = re.compile(r"per day \((?:TPD|RPD)\)", re.IGNORECASE)
_TRY_AGAIN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)


def daily_quota_reset_s(exc: Exception) -> float | None:
    """Seconds until a *daily* quota resets, if `exc` is a daily-quota 429."""
    text = str(exc)
    if not isinstance(exc, LLMTransientError) or not _DAILY.search(text):
        return None
    match = _TRY_AGAIN.search(text)
    if not match or not any(match.groups()):
        return 3600.0
    hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def cooldown_s(exc: Exception) -> float | None:
    """How long to park a route after this failure (None: do not park)."""
    daily = daily_quota_reset_s(exc)
    if daily is not None:
        return daily
    if isinstance(exc, LLMTransientError) and getattr(exc, "status", None) == 429:
        return min(60.0, exc.retry_after or 20.0)
    return None


class LLMRouteError(LLMError):
    """Every route for a tier failed. Carries each route's reason, in order."""

    def __init__(self, tier: str, reasons: list[str]):
        super().__init__(f"all routes for tier {tier!r} failed: " + " | ".join(reasons))
        self.reasons = reasons


class LLMStreamInterrupted(LLMError):
    """A stream failed after tokens had already been sent; no silent fallback possible."""


class ChatModel(Protocol):
    """What the answer service needs. RoutedLLM implements it; tests fake it."""

    ledger: Ledger
    served_by: list[str]

    def stream(
        self, messages: str | list[dict[str, Any]], *, system: str | None = None
    ) -> Iterator[str]: ...

    def complete(
        self, messages: str | list[dict[str, Any]], *, system: str | None = None
    ) -> str: ...

    def complete_structured(
        self,
        messages: str | list[dict[str, Any]],
        schema: type[TModel],
        *,
        system: str | None = None,
    ) -> TModel: ...


class TokenPacer:
    """Sliding-window tokens-per-minute guard, one window per model, plus cooldowns.

    Shared by every RoutedLLM in a process (module-level `PACER`), because the limit is
    per API key and model, not per request.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._clock = clock
        self._sleep = sleep
        self._windows: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._cooling: dict[str, float] = {}
        self.slept_s = 0.0

    def _used(self, model: str, now: float) -> int:
        window = self._windows[model]
        while window and now - window[0][0] >= WINDOW_S:
            window.popleft()
        return sum(tokens for _, tokens in window)

    def wait_needed(self, model: str, limit: int | None, estimate: int) -> float:
        """Seconds until `estimate` more tokens fit under `limit` (0 when they fit now)."""
        if not limit:
            return 0.0
        now = self._clock()
        used = self._used(model, now)
        if used + estimate <= limit:
            return 0.0
        excess = used + estimate - limit
        freed, wait_until = 0, now
        for at, tokens in self._windows[model]:
            freed += tokens
            wait_until = at + WINDOW_S
            if freed >= excess:
                break
        return max(0.0, wait_until - now)

    def wait(self, model: str, limit: int | None, estimate: int) -> float:
        waited = self.wait_needed(model, limit, estimate)
        if waited > 0:
            self._sleep(waited)
            self.slept_s += waited
        return waited

    def cool(self, model: str, seconds: float) -> None:
        self._cooling[model] = max(self._cooling.get(model, 0.0), self._clock() + seconds)

    def cooling_for(self, model: str) -> float:
        return max(0.0, self._cooling.get(model, 0.0) - self._clock())

    def record(self, model: str, tokens: int) -> None:
        if tokens > 0:
            self._windows[model].append((self._clock(), tokens))


PACER = TokenPacer()

LLMFactory = Callable[[Route, Ledger, RetryPolicy, LLMSettings | None], Any]


def default_factory(
    route: Route, ledger: Ledger, retry: RetryPolicy, settings: LLMSettings | None
) -> LLM:
    llm = LLM(
        provider=route.provider,
        model=route.model,
        settings=settings,
        ledger=ledger,
        retry_policy=retry,
        temperature=route.temperature,
        max_tokens=route.max_tokens,
        label=route.model,
        min_interval_s=0.0,  # pacing is the TokenPacer's job; no fixed sleep per call
    )
    # One retry layer, the one the ledger can see (the SDK's own default is 2 retries).
    llm.client = llm.client.with_options(max_retries=0)
    return llm


class RoutedLLM:
    """One tier from routing.toml: the primary route, then each fallback, one Ledger."""

    def __init__(
        self,
        name: str,
        tier: Tier,
        *,
        ledger: Ledger,
        retry: RetryPolicy | None = None,
        settings: LLMSettings | None = None,
        factory: LLMFactory = default_factory,
        pacer: TokenPacer | None = None,
        counter: TokenCounter | None = None,
        max_wait_s: float = 3.0,
        expected_output_tokens: int = 1200,
    ):
        self.name = name
        self.tier = tier
        self.ledger = ledger
        self.retry = retry or RetryPolicy()
        self.settings = settings
        self.factory = factory
        self.pacer = pacer or PACER
        self.counter = counter
        self.max_wait_s = max_wait_s
        self.expected_output_tokens = expected_output_tokens
        self._clients: dict[str, Any] = {}
        self.served_by: list[str] = []
        self.fallback_reasons: list[str] = []

    def _client(self, route: Route) -> Any:
        if route.key not in self._clients:
            self._clients[route.key] = self.factory(route, self.ledger, self.retry, self.settings)
        return self._clients[route.key]

    def _estimate(self, messages: Any, system: str | None) -> int:
        counter = self.counter or default_counter()
        text = (system or "") + (messages if isinstance(messages, str) else str(messages))
        return counter.count(text) + self.expected_output_tokens

    def _admit(self, route: Route, messages: Any, system: str | None, reasons: list[str]) -> bool:
        """Can this route take the call now? Sleeps up to max_wait_s for TPM room."""
        cooling = self.pacer.cooling_for(route.model)
        if cooling:
            reasons.append(f"{route.key}: cooling down for {cooling:.0f}s")
            return False
        if route.tpm_limit:
            needed = self.pacer.wait_needed(
                route.model, route.tpm_limit, self._estimate(messages, system)
            )
            if needed > self.max_wait_s:
                reasons.append(f"{route.key}: tokens-per-minute window full for {needed:.0f}s")
                return False
            if needed:
                self.pacer.wait(route.model, route.tpm_limit, self._estimate(messages, system))
        return True

    @staticmethod
    def _overrides(route: Route) -> dict[str, Any]:
        return {"reasoning_effort": route.reasoning_effort} if route.reasoning_effort else {}

    def _failed(self, route: Route, exc: Exception, reasons: list[str]) -> None:
        reasons.append(f"{route.key}: {type(exc).__name__}: {str(exc)[:300]}")
        pause = cooldown_s(exc)
        if pause:
            self.pacer.cool(route.model, pause)

    def _record_usage(self, route: Route, before: int) -> None:
        used = sum(r.usage.total_tokens for r in self.ledger.records[before:])
        self.pacer.record(route.model, used)

    def _done(self, route: Route, reasons: list[str]) -> None:
        self.served_by.append(route.model)
        self.fallback_reasons.extend(reasons)

    # ------------------------------------------------------------------ calls

    def complete(self, messages: str | list[dict[str, Any]], *, system: str | None = None) -> str:
        reasons: list[str] = []
        for route in self.tier.routes:
            try:
                client = self._client(route)
            except ValueError as exc:
                reasons.append(f"{route.key}: unavailable ({exc})")
                continue
            if not self._admit(route, messages, system, reasons):
                continue
            before = len(self.ledger.records)
            try:
                result = client.complete(
                    messages, system=system, label=self.name, **self._overrides(route)
                )
            except LLMBudgetError:
                raise
            except (LLMTransientError, LLMPermanentError) as exc:
                self._failed(route, exc, reasons)
                continue
            finally:
                self._record_usage(route, before)
            self._done(route, reasons)
            return result.text
        self.fallback_reasons.extend(reasons)
        raise LLMRouteError(self.name, reasons)

    def complete_structured(
        self,
        messages: str | list[dict[str, Any]],
        schema: type[TModel],
        *,
        system: str | None = None,
    ) -> TModel:
        reasons: list[str] = []
        for route in self.tier.routes:
            try:
                client = self._client(route)
            except ValueError as exc:
                reasons.append(f"{route.key}: unavailable ({exc})")
                continue
            if not self._admit(route, messages, system, reasons):
                continue
            for attempt in range(1 + route.schema_retries):
                before = len(self.ledger.records)
                try:
                    result = client.complete_structured(
                        messages, schema, system=system, label=self.name, **self._overrides(route)
                    )
                except LLMBudgetError:
                    raise
                except (LLMTransientError, LLMPermanentError, LLMOutputError) as exc:
                    self._failed(route, exc, reasons)
                    if is_schema_rejection(exc) and attempt < route.schema_retries:
                        continue
                    break
                finally:
                    self._record_usage(route, before)
                self._done(route, reasons)
                return result
        self.fallback_reasons.extend(reasons)
        raise LLMRouteError(self.name, reasons)

    def stream(
        self, messages: str | list[dict[str, Any]], *, system: str | None = None
    ) -> Iterator[str]:
        reasons: list[str] = []
        for route in self.tier.routes:
            try:
                client = self._client(route)
            except ValueError as exc:
                reasons.append(f"{route.key}: unavailable ({exc})")
                continue
            if not self._admit(route, messages, system, reasons):
                continue
            before = len(self.ledger.records)
            started = time.monotonic()
            sent = False
            try:
                for piece in client.stream(
                    messages, system=system, label=self.name, **self._overrides(route)
                ):
                    sent = True
                    yield piece
            except LLMBudgetError:
                raise
            except Exception as exc:
                error = exc if isinstance(exc, LLMError) else classify(exc)
                if len(self.ledger.records) == before:
                    # The request itself failed: llm-kit never recorded it. A failed call
                    # still spent time (and maybe quota), so it goes in the ledger.
                    self.ledger.add(
                        CallRecord(
                            provider=route.provider,
                            model=route.model,
                            label=self.name,
                            usage=Usage(),
                            latency_s=time.monotonic() - started,
                            error=f"{type(error).__name__}: {str(error)[:300]}",
                        )
                    )
                if sent:
                    self._failed(route, error, reasons)
                    raise LLMStreamInterrupted(
                        f"{route.key} failed mid-answer: {str(error)[:200]}"
                    ) from exc
                if not isinstance(error, LLMError):
                    raise
                self._failed(route, error, reasons)
                continue
            finally:
                self._record_usage(route, before)
            self._done(route, reasons)
            return
        self.fallback_reasons.extend(reasons)
        raise LLMRouteError(self.name, reasons)


def usage_summary(ledger: Ledger, served_by: list[str] | None = None) -> dict[str, Any]:
    """The `usage` block stored with every question and sent in the `done` event."""
    total = ledger.total_usage
    by_model: dict[str, dict[str, Any]] = {}
    for record in ledger.records:
        row = by_model.setdefault(
            record.model,
            {
                "model": record.model,
                "provider": record.provider,
                "calls": 0,
                "failed_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "usd": 0.0,
            },
        )
        row["calls"] += 1
        row["failed_calls"] += 1 if record.error else 0
        row["prompt_tokens"] += record.usage.prompt_tokens
        row["completion_tokens"] += record.usage.completion_tokens
        row["reasoning_tokens"] += record.usage.reasoning_tokens
        row["usd"] = round(row["usd"] + record.cost_usd, 8)
    return {
        "calls": len(ledger.records),
        "failed_calls": sum(1 for r in ledger.records if r.error),
        "prompt_tokens": total.prompt_tokens,
        "completion_tokens": total.completion_tokens,
        "reasoning_tokens": total.reasoning_tokens,
        "usd": round(ledger.total_usd, 8),
        "served_by": list(served_by or []),
        "by_model": list(by_model.values()),
    }
