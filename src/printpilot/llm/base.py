"""LLM boundary.

The pipeline depends on this Protocol, never on a vendor SDK. That is what makes
the acceptance requirement "core tests run offline with no API key" achievable:
tests inject :class:`~printpilot.llm.mock.MockLLMClient` and the graph cannot tell
the difference.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMError(RuntimeError):
    """Raised on transport failure, timeout, or unparseable output.

    The fallback layer (M7) catches this and degrades to rule-based decisions
    rather than letting the whole run fail.
    """


class LLMUsage(BaseModel):
    """Per-call accounting. Cost reporting is a deliverable, so it is recorded
    from the first call rather than bolted on later."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient(Protocol):
    """Returns a validated instance of the requested schema, or raises LLMError."""

    @property
    def name(self) -> str: ...

    def complete_structured[ModelT: BaseModel](
        self, *, prompt: str, schema: type[ModelT]
    ) -> ModelT: ...
