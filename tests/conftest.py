"""Shared fixtures: a bag-of-words fake embedder, a scripted fake chat model, an in-memory
corpus, and an Engine wired from them.

No test touches the network: providers are faked or mocked with respx, Postgres is the
MemoryStore (the `postgres` marker tests run only with TEST_DATABASE_URL), tiktoken is
replaced by ApproxCounter where counts matter.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator
from typing import Any

import pytest
from llm_kit import CallRecord, Ledger, Usage
from pydantic import BaseModel

from docpilot.config import AppSettings
from docpilot.db import MemoryStore
from docpilot.embeddings import EmbeddingLedger
from docpilot.engine import Engine
from docpilot.ingest.pipeline import ingest
from docpilot.tokens import ApproxCounter


class FakeEmbedder:
    """Hashed bag-of-words vectors: texts sharing words point the same way."""

    provider = "fake"
    model = "fake-embed"
    dimensions = 64
    max_batch = 100

    def __init__(self) -> None:
        self.ledger = EmbeddingLedger()
        self.calls: list[tuple[int, str]] = []

    def embed(self, texts, input_type):  # type: ignore[no-untyped-def]
        self.calls.append((len(texts), input_type))
        out = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                slot = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dimensions
                vector[slot] += 1.0
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            out.append([v / norm for v in vector])
        return out


class FakeChatModel:
    """Streams a scripted answer and records a priced call in a real Ledger."""

    def __init__(
        self,
        ledger: Ledger,
        answer: str = "Use `scheduleNotificationAsync` [1].",
        structured: BaseModel | None = None,
        fail: Exception | None = None,
    ):
        self.ledger = ledger
        self.answer = answer
        self.structured = structured
        self.fail = fail
        self.served_by: list[str] = []
        self.prompts: list[tuple[Any, str | None]] = []

    def _record(self, prompt: Any) -> None:
        self.ledger.add(
            CallRecord(
                provider="groq",
                model="openai/gpt-oss-120b",
                label="fake",
                usage=Usage(prompt_tokens=len(str(prompt)) // 4, completion_tokens=50),
                latency_s=0.01,
            )
        )
        self.served_by.append("openai/gpt-oss-120b")

    def stream(self, messages, *, system=None) -> Iterator[str]:  # type: ignore[no-untyped-def]
        self.prompts.append((messages, system))
        if self.fail:
            raise self.fail
        self._record(messages)
        yield from re.split(r"(?<= )", self.answer)

    def complete(self, messages, *, system=None) -> str:  # type: ignore[no-untyped-def]
        self.prompts.append((messages, system))
        self._record(messages)
        return "standalone query about notifications"

    def complete_structured(self, messages, schema, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append((messages, system))
        if self.fail:
            raise self.fail
        self._record(messages)
        assert self.structured is not None
        return self.structured


PAGE_V58 = """---
title: Notifications
description: Schedule and receive notifications.
packageName: 'expo-notifications'
platforms: ['android', 'ios']
---

import APISection from '~/components/plugins/APISection';

`expo-notifications` provides an API to present, schedule, receive and respond to notifications.

## Installation

<APIInstallSection />

## Usage

Call scheduleNotificationAsync with a trigger of null to show a notification immediately.

```ts
Notifications.scheduleNotificationAsync({ content: { title: 'Hi' }, trigger: null });
```

## Configuration in app config

Set the `enableBackgroundRemoteNotifications` property of the config plugin to true.
"""

PAGE_V57 = PAGE_V58.replace(
    "enableBackgroundRemoteNotifications", "enableBackgroundRemoteNotificationsLegacy"
)

GUIDE = """---
title: Push notifications setup
---

Follow these steps to set up push notifications with EAS.

## Get credentials

Run `eas credentials` to generate push notification credentials for Android and iOS.
"""

RN_PAGE = """---
id: flatlist
title: FlatList
---

A performant interface for rendering basic, flat lists.

## Props

### `renderItem`

Takes an item from data and renders it into the list.
"""


def build_memory_corpus(store: MemoryStore, embedder: FakeEmbedder) -> None:
    corpora = [
        ("expo", "v58.0.0", {"docs/pages/versions/v58.0.0/sdk/notifications.mdx": PAGE_V58}),
        ("expo", "v57.0.0", {"docs/pages/versions/v57.0.0/sdk/notifications.mdx": PAGE_V57}),
        ("expo", "unversioned", {"docs/pages/push-notifications/setup.mdx": GUIDE}),
        ("react-native", "current", {"docs/flatlist.md": RN_PAGE}),
    ]
    for sdk, version, files in corpora:
        ingest(
            sdk,
            version,
            store=store,
            embedder=embedder,
            files=files,
            commit_sha="a" * 40,
            tpm_limit=None,
            pause_s=0,
        )


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=None,
        groq_api_key="test-groq",
        gemini_api_key="test-gemini",
        web_origin="http://localhost:3600",
        questions_per_hour_per_ip=30,
    )


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def store(embedder: FakeEmbedder) -> MemoryStore:
    memory = MemoryStore()
    build_memory_corpus(memory, embedder)
    return memory


@pytest.fixture
def counter() -> ApproxCounter:
    return ApproxCounter()


def make_engine(settings: AppSettings, store: MemoryStore, embedder: FakeEmbedder, **model_kw):
    models: list[FakeChatModel] = []

    def factory(tier: str, ledger: Ledger) -> FakeChatModel:
        model = FakeChatModel(ledger, **model_kw)
        models.append(model)
        return model

    engine = Engine.build(settings, store=store, embedder=embedder, model_factory=factory)
    engine.models = models  # type: ignore[attr-defined]
    return engine


@pytest.fixture
def engine(settings: AppSettings, store: MemoryStore, embedder: FakeEmbedder) -> Engine:
    return make_engine(settings, store, embedder)
