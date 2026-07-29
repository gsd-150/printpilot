"""Client for any OpenAI-compatible endpoint.

Deliberately not tied to a vendor. The project is configured against a relay
(ChatAnywhere) but nothing here knows that; swapping ``base_url`` and ``model``
is the whole migration.

**Structured output is not assumed.** Relays and domestic providers vary in
whether they support strict ``json_schema``, loose ``json_object``, or neither,
and the support is frequently undocumented. So the flow is always:

    ask for JSON → parse → validate against the pydantic schema → on failure,
    one bounded repair attempt that shows the model its own error

Validation is ours regardless of what the provider promises. A schema violation
is counted rather than silently patched: the rate is a reportable property of the
configuration, not an implementation detail to hide.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from printpilot.llm.base import LLMError, LLMUsage
from printpilot.llm.config import LLMSettings, StructuredMode

if TYPE_CHECKING:  # pragma: no cover
    from openai import OpenAI

_SYSTEM_SUFFIX = "\n\nReturn a single JSON object and nothing else. No prose, no markdown fence."


@dataclass
class OpenAICompatibleClient:
    """Talks to ``/v1/chat/completions`` on whatever host is configured."""

    settings: LLMSettings
    usage: LLMUsage = field(default_factory=LLMUsage)
    schema_violations: int = 0
    repair_attempts: int = 0
    call_count: int = 0
    _client: OpenAI | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return f"openai-compatible:{self.settings.model}"

    def _api(self) -> OpenAI:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_s,
            )
        return self._client

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any] | None:
        match self.settings.structured_mode:
            case StructuredMode.JSON_SCHEMA:
                return {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": schema.model_json_schema(),
                        "strict": True,
                    },
                }
            case StructuredMode.JSON_OBJECT:
                return {"type": "json_object"}
            case StructuredMode.PROMPT_ONLY:
                return None

    def _raw_completion(self, messages: list[dict[str, str]], schema: type[BaseModel]) -> str:
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }
        response_format = self._response_format(schema)
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            completion = self._api().chat.completions.create(**kwargs)
        except Exception as exc:
            msg = f"LLM call failed: {type(exc).__name__}: {exc}"
            raise LLMError(msg) from exc
        finally:
            self.call_count += 1

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._record(completion, elapsed_ms)

        content = completion.choices[0].message.content if completion.choices else None
        if not content:
            msg = "LLM returned an empty message"
            raise LLMError(msg)
        return str(content)

    def _record(self, completion: Any, elapsed_ms: float) -> None:
        usage = getattr(completion, "usage", None)
        self.usage = LLMUsage(
            prompt_tokens=self.usage.prompt_tokens + getattr(usage, "prompt_tokens", 0),
            completion_tokens=(
                self.usage.completion_tokens + getattr(usage, "completion_tokens", 0)
            ),
            latency_ms=self.usage.latency_ms + elapsed_ms,
        )

    def complete_structured[ModelT: BaseModel](
        self, *, prompt: str, schema: type[ModelT]
    ) -> ModelT:
        messages = [
            {"role": "system", "content": _schema_instructions(schema) + _SYSTEM_SUFFIX},
            {"role": "user", "content": prompt},
        ]

        content = self._raw_completion(messages, schema)
        try:
            return _parse(content, schema)
        except LLMError as first_error:
            self.schema_violations += 1
            if self.settings.max_repair_attempts < 1:
                raise

            # One bounded repair. Showing the model its own output and the exact
            # validation error works better than restating the schema, and an
            # unbounded loop would let one bad case dominate the run's cost.
            self.repair_attempts += 1
            messages.extend(
                [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"That response failed validation: {first_error}\n"
                            "Return corrected JSON only."
                        ),
                    },
                ]
            )
            return _parse(self._raw_completion(messages, schema), schema)


def _schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "You produce JSON conforming exactly to this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )


def _strip_fence(text: str) -> str:
    """Models wrap JSON in ``` fences even when told not to."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return body.rsplit("```", 1)[0].strip()


def _parse[ModelT: BaseModel](content: str, schema: type[ModelT]) -> ModelT:
    text = _strip_fence(content)
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        msg = f"response did not satisfy {schema.__name__}: {exc.error_count()} error(s); {exc}"
        raise LLMError(msg) from exc
    except ValueError as exc:
        msg = f"response was not valid JSON: {exc}"
        raise LLMError(msg) from exc
