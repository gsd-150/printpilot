"""The offline LLM stand-in.

Acceptance requirement: core tests run with no API key. That only holds if the
mock is strict — a mock that improvises would let a broken pipeline pass.
"""

from __future__ import annotations

import pytest

from printpilot.domain import DiagnosisResult, FaultCode, Hypothesis, SafetyVerdict
from printpilot.llm import LLMError, LLMUsage, MockLLMClient


def _abstaining_result(case_id: str = "case-0001") -> DiagnosisResult:
    return DiagnosisResult(
        case_id=case_id,
        hypotheses=[
            Hypothesis(fault_code=FaultCode.UNKNOWN, confidence=0.5, reasoning="证据不足。")
        ],
    )


def test_returns_scripted_responses_in_order() -> None:
    first, second = _abstaining_result("a"), _abstaining_result("b")
    client = MockLLMClient(scripted=[first, second])

    assert client.complete_structured(prompt="p1", schema=DiagnosisResult) is first
    assert client.complete_structured(prompt="p2", schema=DiagnosisResult) is second


def test_records_every_call() -> None:
    client = MockLLMClient(scripted=[_abstaining_result()])
    client.complete_structured(prompt="diagnose this", schema=DiagnosisResult)

    assert client.call_count == 1
    assert client.calls[0].prompt == "diagnose this"
    assert client.calls[0].schema_name == "DiagnosisResult"


def test_exhaustion_raises_instead_of_improvising() -> None:
    client = MockLLMClient(scripted=[])
    with pytest.raises(LLMError, match="exhausted"):
        client.complete_structured(prompt="p", schema=DiagnosisResult)


def test_schema_mismatch_raises() -> None:
    client = MockLLMClient(scripted=[_abstaining_result()])
    with pytest.raises(LLMError, match="was requested"):
        client.complete_structured(prompt="p", schema=SafetyVerdict)


def test_can_simulate_an_outage() -> None:
    """Used to exercise the degraded path without needing a real failure."""
    client = MockLLMClient(raises=LLMError("upstream timeout"))
    with pytest.raises(LLMError, match="timeout"):
        client.complete_structured(prompt="p", schema=DiagnosisResult)
    assert client.call_count == 1, "a failed call is still a call, for cost accounting"


def test_client_reports_its_name() -> None:
    assert MockLLMClient().name == "mock"


def test_usage_totals_tokens() -> None:
    usage = LLMUsage(prompt_tokens=120, completion_tokens=45, latency_ms=812.5)
    assert usage.total_tokens == 165
