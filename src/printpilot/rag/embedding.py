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
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from printpilot.llm.base import LLMError
from printpilot.llm.config import LLMSettings

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

#: Lives under ``.chroma/`` because both are regenerable retrieval artifacts and
#: that directory is already gitignored.
DEFAULT_EMBEDDING_CACHE = Path(".chroma/embedding-cache.json")


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
class CachedEmbedder:
    """Wraps any embedder with a persistent text → vector cache.

    Exists because embedding requests are the scarce resource, not embedding
    latency: the corpus is re-indexed on every run and retrieval queries are
    rendered from a small phrase vocabulary, so most texts repeat — and the
    metered endpoint charges (or rate-limits) every repeat. A full ablation run
    was measured hitting a 100-requests/day free-tier ceiling on calls that were
    overwhelmingly re-embeddings of identical text.

    The cache key includes the inner embedder's name, so vectors from different
    models never answer for each other. ``embed`` holds one lock across the API
    call on purpose: concurrent misses of the same text would each spend quota,
    and protecting quota is the whole point; serialized embedding latency is
    noise next to the chat calls that dominate a run.
    """

    inner: Embedder
    path: Path = DEFAULT_EMBEDDING_CACHE
    hits: int = 0
    misses: int = 0
    _memory: dict[str, list[float]] = field(default_factory=dict, repr=False)
    _loaded: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def name(self) -> str:
        return f"cached:{self.inner.name}"

    @property
    def semantic(self) -> bool:
        return self.inner.semantic

    def _key(self, text: str) -> str:
        material = f"{self.inner.name}\x00{text}".encode()
        return hashlib.sha256(material).hexdigest()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._memory = {str(k): [float(x) for x in v] for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            # A missing or corrupt cache is a cold start, not a failure.
            self._memory = {}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._memory), encoding="utf-8")
        tmp.replace(self.path)

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self._load()
            keys = [self._key(text) for text in texts]
            missing = [i for i, key in enumerate(keys) if key not in self._memory]
            self.hits += len(texts) - len(missing)
            self.misses += len(missing)
            if missing:
                fetched = self.inner.embed([texts[i] for i in missing])
                for index, vector in zip(missing, fetched, strict=True):
                    self._memory[keys[index]] = vector
                self._persist()
            return [self._memory[key] for key in keys]


@dataclass
class OpenAIEmbedder:
    """Any OpenAI-compatible ``/v1/embeddings`` endpoint.

    Counter updates are not locked; in production this sits behind
    :class:`CachedEmbedder`, whose lock already serializes calls."""

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
