from collections.abc import Iterator

import openai
import pytest
from llm_kit import Ledger, LLMTransientError
from llm_kit.schema import require_all_properties, to_provider_schema
from pydantic import ValidationError

from docpilot.answer.diff import (
    DiffAnswer,
    DiffChange,
    clean_diff,
    order_versions,
    render_diff,
)
from docpilot.llm import (
    LLMRouteError,
    LLMStreamInterrupted,
    RoutedLLM,
    TokenPacer,
    cooldown_s,
    usage_summary,
)
from docpilot.routing import Route, Tier, load_routing

# ----------------------------------------------------------------------------- diff


def test_diff_schema_requires_every_field_but_allows_null():
    with pytest.raises(ValidationError):
        DiffChange.model_validate({"kind": "added", "subject": "x", "citations": [1]})
    change = DiffChange.model_validate(
        {"kind": "added", "subject": "x", "before": None, "after": "y", "citations": [1]}
    )
    assert change.before is None
    with pytest.raises(ValidationError):
        DiffChange.model_validate(
            {"kind": "changed", "subject": "x", "before": None, "after": None, "citations": []}
        )
    schema = require_all_properties(to_provider_schema(DiffAnswer))
    assert set(schema["required"]) == {"summary", "changes", "missing"}


def test_clean_diff_drops_unsupported_changes_and_render_keeps_citations():
    diff = DiffAnswer(
        summary="The option was renamed [1][3].",
        changes=[
            DiffChange(
                kind="renamed", subject="`foo`", before="foo", after="bar", citations=[1, 3, 3]
            ),
            DiffChange(kind="added", subject="`baz`", before=None, after="new", citations=[9]),
        ],
        missing=None,
    )
    cleaned, dropped = clean_diff(diff, [1, 2, 3])
    assert dropped == 1 and cleaned.changes[0].citations == [1, 3]
    text = render_diff(cleaned, "Expo SDK 57", "Expo SDK 58")
    assert "**Expo SDK 57 → Expo SDK 58**" in text
    assert "- **Renamed** `foo`: foo → bar [1][3]" in text


def test_versions_are_ordered_older_first():
    assert order_versions("v58.0.0", "v57.0.0") == ("v57.0.0", "v58.0.0")
    assert order_versions("v9.0.0", "v10.0.0") == ("v9.0.0", "v10.0.0")


# ----------------------------------------------------------------------------- routing


def test_routing_table_loads_and_every_model_is_priced():
    routing = load_routing()
    assert routing.tier("answer").routes[0].key == "groq:openai/gpt-oss-120b"
    assert routing.tier("answer").routes[1].provider == "gemini"
    assert routing.unpriced_models() == []


# ----------------------------------------------------------------------------- RoutedLLM


class ScriptedClient:
    def __init__(self, ledger: Ledger, pieces=("Hello ", "[1]"), fail_at: int | None = None):
        self.ledger, self.pieces, self.fail_at = ledger, pieces, fail_at

    def stream(self, messages, *, system=None, label=None, **kw) -> Iterator[str]:  # type: ignore[no-untyped-def]
        for i, piece in enumerate(self.pieces):
            if self.fail_at == i:
                raise LLMTransientError("429 from provider", status=429, retry_after=5)
            yield piece

    def complete(self, messages, *, system=None, label=None, **kw):  # type: ignore[no-untyped-def]
        raise LLMTransientError("Limit per day (TPD): try again in 2m30s", status=429)


TIER = Tier(
    provider="groq",
    model="m1",
    tpm_limit=8000,
    fallbacks=[Route(provider="gemini", model="m2")],
)


def make(clients: dict[str, ScriptedClient], pacer: TokenPacer, ledger: Ledger) -> RoutedLLM:
    return RoutedLLM(
        "answer",
        TIER,
        ledger=ledger,
        factory=lambda route, *_: clients[route.model],
        pacer=pacer,
        counter=type("C", (), {"name": "c", "count": staticmethod(len)})(),
    )


def test_stream_falls_back_before_the_first_token_and_parks_the_route():
    ledger, pacer = Ledger(), TokenPacer()
    clients = {"m1": ScriptedClient(ledger, fail_at=0), "m2": ScriptedClient(ledger, ("Hi",))}
    llm = make(clients, pacer, ledger)
    assert "".join(llm.stream("q")) == "Hi"
    assert llm.served_by == ["m2"]
    assert pacer.cooling_for("m1") > 0
    # The failed request is in the ledger even though llm-kit never recorded it.
    assert ledger.records[0].error and ledger.records[0].model == "m1"
    # The parked route is skipped next time without being called.
    assert "".join(make(clients, pacer, ledger).stream("q")) == "Hi"


def test_stream_failure_after_tokens_is_reported_not_hidden():
    ledger = Ledger()
    clients = {"m1": ScriptedClient(ledger, ("a", "b"), fail_at=1), "m2": ScriptedClient(ledger)}
    with pytest.raises(LLMStreamInterrupted):
        list(make(clients, TokenPacer(), ledger).stream("q"))


def test_full_tpm_window_takes_the_fallback_instead_of_waiting():
    ledger, pacer = Ledger(), TokenPacer()
    pacer.record("m1", 7900)
    clients = {"m1": ScriptedClient(ledger, ("slow",)), "m2": ScriptedClient(ledger, ("fast",))}
    llm = make(clients, pacer, ledger)
    assert "".join(llm.stream("q" * 500)) == "fast"
    assert "tokens-per-minute" in llm.fallback_reasons[0]


def test_all_routes_failing_raises_with_reasons():
    ledger, pacer = Ledger(), TokenPacer()
    clients = {"m1": ScriptedClient(ledger), "m2": ScriptedClient(ledger)}
    with pytest.raises(LLMRouteError) as info:
        make(clients, pacer, ledger).complete("q")
    assert len(info.value.reasons) == 2
    assert pacer.cooling_for("m1") == pytest.approx(150, abs=1)


def test_unclassified_sdk_errors_are_classified():
    error = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
    from llm_kit import classify

    assert isinstance(classify(error), LLMTransientError)
    assert cooldown_s(LLMTransientError("x", status=500)) is None


def test_usage_summary_totals():
    from llm_kit import CallRecord, Usage

    ledger = Ledger()
    ledger.add(CallRecord("groq", "openai/gpt-oss-120b", "a", Usage(1000, 200, 50), 0.5))
    summary = usage_summary(ledger, ["openai/gpt-oss-120b"])
    assert summary["prompt_tokens"] == 1000 and summary["calls"] == 1
    assert summary["usd"] == pytest.approx((1000 * 0.15 + 200 * 0.60) / 1e6)
