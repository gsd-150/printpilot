"""Embedding backends.

Two, for different jobs:

* :class:`OpenAIEmbedder` — the real one, through whatever OpenAI-compatible
  endpoint is configured. Used for every reported retrieval number.
* :class:`DeterministicEmbedder` — a hashed bag-of-trigrams. It is **not
  semantic** and never produces a reported metric. It exists so the store, the
  metadata filtering and the ranking plumbing can be tested offline with no key,
  which the acceptance criteria require.

Keeping the fake obviously fake matters. An embedder that looked plausible would
invite someone to quote a Hit@k produced by it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from printpilot.llm.base import LLMError
from printpilot.llm.config import LLMSettings

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def semantic(self) -> bool:
        """False for stand-ins. Reported metrics must come from a semantic one."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class DeterministicEmbedder:
    """Hashed character trigrams. Offline, reproducible, and not semantic.

    Retrieval built on this will match on surface overlap and nothing else. That is
    enough to exercise the plumbing and useless as evidence about retrieval quality,
    which is exactly the intent.
    """

    dimensions: int = 256

    @property
    def name(self) -> str:
        return f"deterministic-trigram-{self.dimensions}"

    @property
    def semantic(self) -> bool:
        return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            packed = "".join(text.split())
            vector = [0.0] * self.dimensions
            for i in range(max(0, len(packed) - 2)):
                trigram = packed[i : i + 3]
                digest = hashlib.blake2b(trigram.encode("utf-8"), digest_size=4).digest()
                vector[int.from_bytes(digest, "big") % self.dimensions] += 1.0
            norm = sum(v * v for v in vector) ** 0.5
            vectors.append([v / norm for v in vector] if norm else vector)
        return vectors


@dataclass
class OpenAIEmbedder:
    """Any OpenAI-compatible ``/v1/embeddings`` endpoint."""

    settings: LLMSettings
    model: str = DEFAULT_EMBEDDING_MODEL
    batch_size: int = 64
    calls: int = 0
    tokens: int = 0
    _client: object | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return f"openai:{self.model}"

    @property
    def semantic(self) -> bool:
        return True

    def _api(self) -> object:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_s,
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            try:
                response = self._api().embeddings.create(model=self.model, input=batch)  # type: ignore[attr-defined]
            except Exception as exc:
                msg = f"embedding call failed: {type(exc).__name__}: {exc}"
                raise LLMError(msg) from exc
            self.calls += 1
            self.tokens += getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
            out.extend(item.embedding for item in response.data)
        return out
