"""LLM configuration and the OpenAI-compatible client.

Everything here runs offline. The network client is exercised against a fake API
object, so the repair path and the parsing rules are covered without spending
tokens or requiring a key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from printpilot.llm import (
    LLMError,
    LLMSettings,
    StructuredMode,
    load_embedding_settings,
    load_settings,
)
from printpilot.llm.config import Backend
from printpilot.llm.openai_compatible import OpenAICompatibleClient, _parse, _strip_fence
from printpilot.llm.probe import ModeResult, ProbeReport


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str
    count: int


def _write_env(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


class TestSettingsLoading:
    def test_inline_comment_is_not_part_of_the_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug that actually happened: a template line reading
        `PRINTPILOT_LLM_BACKEND=openai   # mock | openai` produced the backend
        value "openai       # mock | openai" under naive parsing."""
        monkeypatch.delenv("PRINTPILOT_LLM_BACKEND", raising=False)
        env = _write_env(
            tmp_path,
            "PRINTPILOT_LLM_BACKEND=openai        # mock | openai\n"
            "PRINTPILOT_LLM_MODEL=some-model\n",
        )
        settings = load_settings(env)
        assert settings.backend is Backend.OPENAI

    def test_unknown_backend_falls_back_to_mock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defaulting to the offline client is the safe direction to fail."""
        monkeypatch.delenv("PRINTPILOT_LLM_BACKEND", raising=False)
        env = _write_env(tmp_path, "PRINTPILOT_LLM_BACKEND=typo\n")
        assert load_settings(env).backend is Backend.MOCK

    def test_blank_base_url_means_none_not_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty string would be passed to the SDK as a real base_url."""
        monkeypatch.delenv("PRINTPILOT_LLM_BASE_URL", raising=False)
        env = _write_env(tmp_path, "PRINTPILOT_LLM_BASE_URL=\n")
        assert load_settings(env).base_url is None


class TestEmbeddingSettings:
    _VARS = (
        "PRINTPILOT_EMBEDDING_BASE_URL",
        "PRINTPILOT_EMBEDDING_API_KEY",
        "PRINTPILOT_LLM_BASE_URL",
        "OPENAI_API_KEY",
    )

    def _clear(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in self._VARS:
            monkeypatch.delenv(name, raising=False)

    def test_unset_embedding_vars_inherit_the_chat_endpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The original single-relay configuration must keep working unchanged."""
        self._clear(monkeypatch)
        env = _write_env(
            tmp_path,
            "PRINTPILOT_LLM_BASE_URL=https://relay.example/v1\nOPENAI_API_KEY=chat-key\n",
        )
        settings = load_embedding_settings(env)
        assert settings.base_url == "https://relay.example/v1"
        assert settings.api_key == "chat-key"

    def test_embedding_vars_override_chat_for_embedding_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Chat on a host with no /v1/embeddings forces the split configuration."""
        self._clear(monkeypatch)
        env = _write_env(
            tmp_path,
            "PRINTPILOT_LLM_BASE_URL=https://chat.example/v1\n"
            "OPENAI_API_KEY=chat-key\n"
            "PRINTPILOT_EMBEDDING_BASE_URL=https://embed.example/v1\n"
            "PRINTPILOT_EMBEDDING_API_KEY=embed-key\n",
        )
        embedding = load_embedding_settings(env)
        assert embedding.base_url == "https://embed.example/v1"
        assert embedding.api_key == "embed-key"
        chat = load_settings(env)
        assert chat.base_url == "https://chat.example/v1"
        assert chat.api_key == "chat-key"

    def test_blank_embedding_vars_fall_back_rather_than_emptying(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blank line in the template must not send the SDK an empty base_url."""
        self._clear(monkeypatch)
        env = _write_env(
            tmp_path,
            "PRINTPILOT_LLM_BASE_URL=https://relay.example/v1\n"
            "OPENAI_API_KEY=chat-key\n"
            "PRINTPILOT_EMBEDDING_BASE_URL=\n"
            "PRINTPILOT_EMBEDDING_API_KEY=\n",
        )
        settings = load_embedding_settings(env)
        assert settings.base_url == "https://relay.example/v1"
        assert settings.api_key == "chat-key"


class TestSecrecy:
    def test_describe_never_reveals_the_key(self) -> None:
        settings = LLMSettings(api_key="sk-abcdef1234567890", model="m")
        rendered = settings.describe()
        assert "sk-abcdef1234567890" not in rendered
        assert "已设置" in rendered

    def test_repr_never_reveals_the_key(self) -> None:
        settings = LLMSettings(api_key="sk-abcdef1234567890", model="m")
        assert "sk-abcdef" not in repr(settings)

    def test_configured_requires_both_key_and_model(self) -> None:
        assert not LLMSettings(api_key="k").configured
        assert not LLMSettings(model="m").configured
        assert LLMSettings(api_key="k", model="m").configured


class TestParsing:
    def test_plain_json(self) -> None:
        assert _parse('{"verdict":"ok","count":3}', Answer).count == 3

    def test_strips_a_markdown_fence(self) -> None:
        """Models add fences even when told not to."""
        fenced = '```json\n{"verdict":"ok","count":3}\n```'
        assert _parse(fenced, Answer).verdict == "ok"

    def test_strip_fence_leaves_unfenced_text_alone(self) -> None:
        assert _strip_fence('  {"a":1} ') == '{"a":1}'

    def test_invalid_json_raises_llm_error(self) -> None:
        with pytest.raises(LLMError, match=r"not valid JSON|did not satisfy"):
            _parse("not json at all", Answer)

    def test_extra_field_is_rejected(self) -> None:
        """extra="forbid" means an invented key fails rather than being ignored."""
        with pytest.raises(LLMError, match="did not satisfy"):
            _parse('{"verdict":"ok","count":3,"invented":1}', Answer)

    def test_wrong_type_is_rejected(self) -> None:
        with pytest.raises(LLMError, match="did not satisfy"):
            _parse('{"verdict":"ok","count":"three"}', Answer)


class _FakeCompletions:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        content = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()
        return type("R", (), {"choices": [choice], "usage": usage})()


class _FakeAPI:
    def __init__(self, replies: list[str]) -> None:
        self.completions = _FakeCompletions(replies)
        self.chat = type("Chat", (), {"completions": self.completions})()


def _client(replies: list[str], **overrides: Any) -> OpenAICompatibleClient:
    settings = LLMSettings(api_key="k", model="m", **overrides)
    client = OpenAICompatibleClient(settings=settings)
    client._client = _FakeAPI(replies)  # type: ignore[assignment]
    return client


class TestClientBehaviour:
    def test_happy_path(self) -> None:
        client = _client(['{"verdict":"ok","count":3}'])
        assert client.complete_structured(prompt="p", schema=Answer).count == 3
        assert client.schema_violations == 0

    def test_records_token_usage(self) -> None:
        client = _client(['{"verdict":"ok","count":3}'])
        client.complete_structured(prompt="p", schema=Answer)
        assert client.usage.total_tokens == 15
        assert client.usage.latency_ms > 0

    def test_repairs_once_then_succeeds(self) -> None:
        client = _client(["not json", '{"verdict":"ok","count":3}'])
        assert client.complete_structured(prompt="p", schema=Answer).count == 3
        assert client.schema_violations == 1
        assert client.repair_attempts == 1
        assert client.call_count == 2

    def test_repair_shows_the_model_its_own_error(self) -> None:
        client = _client(["not json", '{"verdict":"ok","count":3}'])
        client.complete_structured(prompt="p", schema=Answer)
        follow_up = client._client.completions.calls[1]["messages"]  # type: ignore[union-attr]
        assert follow_up[-2]["role"] == "assistant"
        assert "failed validation" in follow_up[-1]["content"]

    def test_repair_is_bounded(self) -> None:
        """An unbounded loop would let one bad case dominate a run's cost."""
        client = _client(["not json", "still not json"])
        with pytest.raises(LLMError):
            client.complete_structured(prompt="p", schema=Answer)
        assert client.call_count == 2

    def test_repair_can_be_disabled(self) -> None:
        client = _client(["not json"], max_repair_attempts=0)
        with pytest.raises(LLMError):
            client.complete_structured(prompt="p", schema=Answer)
        assert client.call_count == 1

    def test_violations_are_counted_not_hidden(self) -> None:
        """The rate is a reportable property of the configuration."""
        client = _client(["not json", '{"verdict":"ok","count":3}'])
        client.complete_structured(prompt="p", schema=Answer)
        assert client.schema_violations == 1

    def test_empty_response_is_an_error(self) -> None:
        client = _client([""])
        with pytest.raises(LLMError, match="empty message"):
            client.complete_structured(prompt="p", schema=Answer)

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (StructuredMode.JSON_SCHEMA, "json_schema"),
            (StructuredMode.JSON_OBJECT, "json_object"),
        ],
    )
    def test_response_format_follows_the_mode(self, mode: StructuredMode, expected: str) -> None:
        client = _client(['{"verdict":"ok","count":3}'], structured_mode=mode)
        client.complete_structured(prompt="p", schema=Answer)
        sent = client._client.completions.calls[0]  # type: ignore[union-attr]
        assert sent["response_format"]["type"] == expected

    def test_prompt_only_mode_sends_no_response_format(self) -> None:
        client = _client(['{"verdict":"ok","count":3}'], structured_mode=StructuredMode.PROMPT_ONLY)
        client.complete_structured(prompt="p", schema=Answer)
        assert "response_format" not in client._client.completions.calls[0]  # type: ignore[union-attr]

    @pytest.mark.parametrize("mode", list(StructuredMode))
    def test_every_mode_carries_the_schema_in_the_prompt(self, mode: StructuredMode) -> None:
        """Including strict json_schema, where it also travels in response_format.

        Dropping the duplicate looked like an obvious saving and was tried. Measured
        over the same 20 cases: violation rate 9% -> 50%, calls 22 -> 40, tokens
        99.5k -> 201.7k, because every failure cost a repair round-trip. On this
        relay the mode is forwarded but not enforced — support and enforcement are
        different questions, and the probe only established the first.
        """
        client = _client(['{"verdict":"ok","count":3}'], structured_mode=mode)
        client.complete_structured(prompt="p", schema=Answer)
        system = client._client.completions.calls[0]["messages"][0]["content"]  # type: ignore[union-attr]
        assert "JSON Schema" in system, mode

    def test_temperature_is_pinned_to_zero(self) -> None:
        client = _client(['{"verdict":"ok","count":3}'])
        client.complete_structured(prompt="p", schema=Answer)
        assert client._client.completions.calls[0]["temperature"] == 0.0  # type: ignore[union-attr]


class TestProbeVerdict:
    """A mode is only usable if it works on the schema the pipeline sends."""

    def test_toy_success_alone_does_not_promote_a_mode(self) -> None:
        report = ProbeReport(
            reachable=True,
            modes=[
                ModeResult(StructuredMode.JSON_SCHEMA, "ProbeAnswer", ok=True),
                ModeResult(StructuredMode.JSON_SCHEMA, "DiagnosisResult", ok=False),
                ModeResult(StructuredMode.JSON_OBJECT, "ProbeAnswer", ok=True),
                ModeResult(StructuredMode.JSON_OBJECT, "DiagnosisResult", ok=True),
            ],
        )
        assert report.best_mode is StructuredMode.JSON_OBJECT

    def test_prefers_the_strictest_mode_that_works(self) -> None:
        report = ProbeReport(
            reachable=True,
            modes=[
                ModeResult(StructuredMode.JSON_SCHEMA, "DiagnosisResult", ok=True),
                ModeResult(StructuredMode.JSON_OBJECT, "DiagnosisResult", ok=True),
            ],
        )
        assert report.best_mode is StructuredMode.JSON_SCHEMA

    def test_no_working_mode_yields_none(self) -> None:
        report = ProbeReport(
            reachable=False,
            modes=[ModeResult(StructuredMode.JSON_OBJECT, "DiagnosisResult", ok=False)],
        )
        assert report.best_mode is None
