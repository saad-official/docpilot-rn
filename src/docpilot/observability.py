"""Optional Langfuse export of a question's call records, plus structured logging.

Same approach as Changelog Forge: llm-kit has no tracing hook, and the Langfuse SDK is a
large dependency for one POST per question. After a question finishes, its Ledger records
(model, tokens, cost, latency, errors - never prompt or answer text) go to Langfuse's public
ingestion API as one trace with one generation per call. Off unless both keys are set;
failures are logged and swallowed (observability must never break an answer).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from llm_kit import Ledger

from .config import AppSettings
from .models import utcnow

log = logging.getLogger(__name__)


def langfuse_batch(trace_id: str, ledger: Ledger, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    now = utcnow().isoformat()
    batch: list[dict[str, Any]] = [
        {
            "id": str(uuid4()),
            "timestamp": now,
            "type": "trace-create",
            "body": {"id": trace_id, "name": "docpilot.ask", "metadata": metadata},
        }
    ]
    for record in ledger.records:
        start = record.started_at or now
        try:
            end = (datetime.fromisoformat(start) + timedelta(seconds=record.latency_s)).isoformat()
        except ValueError:
            end = start
        batch.append(
            {
                "id": str(uuid4()),
                "timestamp": now,
                "type": "generation-create",
                "body": {
                    "id": str(uuid4()),
                    "traceId": trace_id,
                    "name": record.label,
                    "model": record.model,
                    "startTime": start,
                    "endTime": end,
                    "usageDetails": {
                        "input": record.usage.prompt_tokens,
                        "output": record.usage.completion_tokens,
                    },
                    "costDetails": {"total": record.cost_usd},
                    "metadata": {
                        "provider": record.provider,
                        "reasoning_tokens": record.usage.reasoning_tokens,
                        "attempts": record.attempts,
                        "finish_reason": record.finish_reason,
                    },
                    "level": "ERROR" if record.error else "DEFAULT",
                    "statusMessage": record.error,
                },
            }
        )
    return batch


def export_question(
    settings: AppSettings,
    trace_id: str,
    ledger: Ledger,
    metadata: dict[str, Any],
    *,
    client: httpx.Client | None = None,
) -> bool:
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return False
    auth = (
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
    )
    http = client or httpx.Client(timeout=5.0)
    try:
        response = http.post(
            f"{settings.langfuse_host.rstrip('/')}/api/public/ingestion",
            json={"batch": langfuse_batch(trace_id, ledger, metadata)},
            auth=auth,
        )
        if response.status_code >= 300:
            log.warning("langfuse ingestion returned %s", response.status_code)
            return False
        return True
    except httpx.HTTPError as exc:
        log.warning("langfuse ingestion failed: %s", exc)
        return False
    finally:
        if client is None:
            http.close()


class JsonFormatter(logging.Formatter):
    """One JSON object per line: what Vercel's log search can filter on."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "at": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(getattr(h, "_docpilot", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._docpilot = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
