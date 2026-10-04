"""Load `routing.toml` into typed objects. The table is config, not code, so a model swap
is a one-line reviewed diff, and every question stores the route that served it."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from llm_kit import RetryPolicy, price_for
from pydantic import BaseModel, Field


class Route(BaseModel):
    provider: str
    model: str
    max_tokens: int = 2048
    temperature: float = 0.2
    reasoning_effort: str | None = None
    tpm_limit: int | None = None
    # Extra draws on the same route when the provider rejects output against the strict
    # schema (Groq's 400 json_validate_failed). Cheaper than jumping to the fallback.
    schema_retries: int = 0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


class Tier(Route):
    fallbacks: list[Route] = Field(default_factory=list)

    @property
    def routes(self) -> list[Route]:
        primary = Route(**self.model_dump(exclude={"fallbacks"}))
        return [primary, *self.fallbacks]


class RetryConfig(BaseModel):
    max_attempts: int = 2
    max_delay_s: float = 4.0
    deadline_s: float = 10.0

    def policy(self) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=self.max_attempts, max_delay_s=self.max_delay_s, deadline_s=self.deadline_s
        )


class Budget(BaseModel):
    max_usd_per_question: float = 0.02


class Routing(BaseModel):
    version: str
    budget: Budget = Field(default_factory=Budget)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    prompts: dict[str, str] = Field(default_factory=dict)
    tiers: dict[str, Tier]

    def tier(self, name: str) -> Tier:
        if name not in self.tiers:
            raise KeyError(f"routing.toml has no tier {name!r}")
        return self.tiers[name]

    def unpriced_models(self) -> list[str]:
        return [
            route.model
            for tier in self.tiers.values()
            for route in tier.routes
            if not price_for(route.model)[1]
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tiers": {name: [r.key for r in tier.routes] for name, tier in self.tiers.items()},
        }


@lru_cache
def load_routing(path: str | None = None) -> Routing:
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    else:
        raw = (resources.files("docpilot") / "routing.toml").read_text(encoding="utf-8")
    return Routing.model_validate(tomllib.loads(raw))
