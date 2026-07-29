"""LLM configuration from the environment.

Loaded through ``python-dotenv`` rather than hand-parsed. The first attempt at
configuring this project put a trailing ``# mock | openai`` comment into the value
of a variable, which a naive ``split("=")`` happily accepted — so the parsing is
delegated to a library that handles the format properly, and the template no longer
uses inline comments.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class Backend(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"


class StructuredMode(StrEnum):
    """How the provider is asked to return parseable JSON.

    Support varies widely across OpenAI-compatible relays and is often
    undocumented, so this is *probed* by ``printpilot llm-check`` rather than
    assumed. Whatever the mode, the response is still validated against the
    pydantic schema on our side.
    """

    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_ONLY = "prompt_only"


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Backend = Backend.MOCK
    base_url: str | None = None
    model: str = ""
    api_key: str = Field(default="", repr=False)
    structured_mode: StructuredMode = StructuredMode.JSON_OBJECT
    temperature: float = 0.0
    timeout_s: float = 60.0
    max_repair_attempts: int = 1

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and bool(self.model)

    def describe(self) -> str:
        """Human-readable summary. Never includes the key."""
        key = "已设置" if self.api_key else "未设置"
        return (
            f"backend={self.backend.value}  base_url={self.base_url or '(默认 OpenAI)'}  "
            f"model={self.model or '(未设置)'}  api_key={key}  mode={self.structured_mode.value}"
        )


def load_settings(env_file: Path | None = None) -> LLMSettings:
    load_dotenv(env_file, override=False)

    raw_backend = os.getenv("PRINTPILOT_LLM_BACKEND", "mock").strip()
    backend = Backend(raw_backend) if raw_backend in set(Backend) else Backend.MOCK

    raw_mode = os.getenv("PRINTPILOT_LLM_STRUCTURED_MODE", "").strip()
    mode = (
        StructuredMode(raw_mode) if raw_mode in set(StructuredMode) else StructuredMode.JSON_OBJECT
    )

    base_url = os.getenv("PRINTPILOT_LLM_BASE_URL", "").strip() or None
    return LLMSettings(
        backend=backend,
        base_url=base_url,
        model=os.getenv("PRINTPILOT_LLM_MODEL", "").strip(),
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        structured_mode=mode,
    )


def load_embedding_settings(env_file: Path | None = None) -> LLMSettings:
    """Settings for the embedding endpoint, which may differ from the chat one.

    Not every chat provider serves embeddings: DeepSeek's official API, for one,
    has no ``/v1/embeddings``. So chat against one host with embeddings against
    another is a real deployment shape, not an edge case. The two variables below
    override the chat endpoint for embedding calls only; left unset, the chat
    endpoint serves both, which is the original single-relay configuration.
    """
    chat = load_settings(env_file)
    base_url = os.getenv("PRINTPILOT_EMBEDDING_BASE_URL", "").strip() or chat.base_url
    api_key = os.getenv("PRINTPILOT_EMBEDDING_API_KEY", "").strip() or chat.api_key
    return chat.model_copy(update={"base_url": base_url, "api_key": api_key})
