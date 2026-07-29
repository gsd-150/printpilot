"""Offline, deterministic LLM stand-in.

Scripted responses are consumed in order. Anything the client is asked for beyond
the script is an error rather than an invented value — a mock that quietly
improvises would let a broken pipeline pass its tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from printpilot.llm.base import LLMError, LLMUsage


@dataclass(frozen=True)
class RecordedCall:
    prompt: str
    schema_name: str


@dataclass
class MockLLMClient:
    """Deterministic client for tests and for ``PRINTPILOT_LLM_BACKEND=mock``.

    Args:
        scripted: Responses handed out in order, one per call.
        raises: If set, every call raises this instead — used to exercise the
            degraded path without needing a real outage.
    """

    scripted: Sequence[BaseModel] = ()
    raises: Exception | None = None
    calls: list[RecordedCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    _cursor: int = 0

    @property
    def name(self) -> str:
        return "mock"

    def complete_structured[ModelT: BaseModel](
        self, *, prompt: str, schema: type[ModelT]
    ) -> ModelT:
        self.calls.append(RecordedCall(prompt=prompt, schema_name=schema.__name__))

        if self.raises is not None:
            raise self.raises

        if self._cursor >= len(self.scripted):
            msg = (
                f"MockLLMClient exhausted: call #{self._cursor + 1} requested "
                f"{schema.__name__}, but only {len(self.scripted)} response(s) were scripted"
            )
            raise LLMError(msg)

        response = self.scripted[self._cursor]
        self._cursor += 1

        if not isinstance(response, schema):
            msg = (
                f"scripted response #{self._cursor} is {type(response).__name__}, "
                f"but {schema.__name__} was requested"
            )
            raise LLMError(msg)
        return response

    @property
    def call_count(self) -> int:
        return len(self.calls)
