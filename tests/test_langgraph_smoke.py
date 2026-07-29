"""M2 acceptance: prove LangGraph does what M4/M7 need, and pin what it does not.

This is deliberately a test rather than a scratch script. A framework evaluation
that only ever ran once on the author's machine is not evidence; a test that runs
in CI on two operating systems is.

The graph below is a miniature of the real pipeline: a deterministic node, an
LLM-backed node fed by the offline mock, and a conditional edge that routes on a
safety verdict rather than falling through to execution.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from printpilot.domain import (
    DiagnosisResult,
    FaultCode,
    Hypothesis,
    SafetyDecision,
    SignalFeature,
)
from printpilot.llm import MockLLMClient
from printpilot.workflow import NodeContractError, StateNodeFn, validating_node


class MiniState(BaseModel):
    """Stand-in for the real pipeline state (M4)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    flow_ratio: float = 1.0
    top_fault: FaultCode | None = None
    decision: SafetyDecision | None = None
    trail: list[str] = []


def _perceive(state: MiniState) -> dict[str, Any]:
    """Deterministic node: no LLM involved."""
    feature = SignalFeature(
        name="flow_ratio_mean", value=0.62, unit="ratio", threshold=0.85, exceeded=True
    )
    return {"flow_ratio": feature.value, "trail": [*state.trail, "perceive"]}


def _diagnose_with(client: MockLLMClient) -> StateNodeFn[MiniState]:
    def _diagnose(state: MiniState) -> dict[str, Any]:
        result = client.complete_structured(
            prompt=f"flow_ratio={state.flow_ratio}", schema=DiagnosisResult
        )
        return {"top_fault": result.top.fault_code, "trail": [*state.trail, "diagnose"]}

    return _diagnose


def _safety_gate(state: MiniState) -> dict[str, Any]:
    """Clogs never reach the parameter path — the gate is plain Python."""
    blocked = state.top_fault in {FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL}
    decision = SafetyDecision.BLOCK if blocked else SafetyDecision.ALLOW
    return {"decision": decision, "trail": [*state.trail, "safety_gate"]}


def _execute(state: MiniState) -> dict[str, Any]:
    return {"trail": [*state.trail, "execute"]}


def _escalate(state: MiniState) -> dict[str, Any]:
    return {"trail": [*state.trail, "escalate"]}


def _route(state: MiniState) -> Literal["execute", "escalate"]:
    return "execute" if state.decision is SafetyDecision.ALLOW else "escalate"


def _build_graph(client: MockLLMClient) -> Any:
    graph = StateGraph(MiniState)
    graph.add_node("perceive", validating_node(MiniState, _perceive))
    graph.add_node("diagnose", validating_node(MiniState, _diagnose_with(client)))
    graph.add_node("safety_gate", validating_node(MiniState, _safety_gate))
    graph.add_node("execute", validating_node(MiniState, _execute))
    graph.add_node("escalate", validating_node(MiniState, _escalate))

    graph.add_edge(START, "perceive")
    graph.add_edge("perceive", "diagnose")
    graph.add_edge("diagnose", "safety_gate")
    graph.add_conditional_edges(
        "safety_gate", _route, {"execute": "execute", "escalate": "escalate"}
    )
    graph.add_edge("execute", END)
    graph.add_edge("escalate", END)
    return graph.compile()


def _scripted(fault: FaultCode) -> DiagnosisResult:
    from printpilot.domain import EvidenceKind, EvidenceRef

    return DiagnosisResult(
        case_id="case-0001",
        hypotheses=[
            Hypothesis(
                fault_code=fault,
                confidence=0.82,
                reasoning="流量比低于阈值。",
                evidence=[EvidenceRef(kind=EvidenceKind.SIGNAL, ref="flow_ratio_series")],
            )
        ],
    )


class TestFrameworkCapabilities:
    """What M4 and M7 depend on."""

    def test_clog_is_routed_away_from_execution(self) -> None:
        client = MockLLMClient(scripted=[_scripted(FaultCode.CLOG_PARTIAL)])
        final = _build_graph(client).invoke(MiniState(case_id="case-0001"))

        assert final["decision"] is SafetyDecision.BLOCK
        assert final["trail"] == ["perceive", "diagnose", "safety_gate", "escalate"]
        assert "execute" not in final["trail"], "a clog must never reach the execution node"

    def test_param_fixable_fault_reaches_execution(self) -> None:
        client = MockLLMClient(scripted=[_scripted(FaultCode.UNDEREXT_PARAM)])
        final = _build_graph(client).invoke(MiniState(case_id="case-0001"))

        assert final["decision"] is SafetyDecision.ALLOW
        assert final["trail"][-1] == "execute"

    def test_llm_node_is_driven_by_the_offline_mock(self) -> None:
        """No API key anywhere in this suite."""
        client = MockLLMClient(scripted=[_scripted(FaultCode.THERMAL_DRIFT)])
        _build_graph(client).invoke(MiniState(case_id="case-0001"))

        assert client.call_count == 1
        assert client.calls[0].schema_name == "DiagnosisResult"

    def test_invoke_returns_a_plain_dict(self) -> None:
        """Worth pinning: the result is a dict, not an instance of the state model,
        so downstream code must not assume attribute access."""
        client = MockLLMClient(scripted=[_scripted(FaultCode.UNDEREXT_PARAM)])
        final = _build_graph(client).invoke(MiniState(case_id="case-0001"))
        assert isinstance(final, dict)


class TestValidationGap:
    """LangGraph does not validate what a node writes back. These tests pin the
    observed behaviour so a future upgrade that changes it is noticed."""

    @staticmethod
    def _run(node: Any) -> dict[str, Any]:
        graph = StateGraph(MiniState)
        graph.add_node("n", node)
        graph.add_edge(START, "n")
        graph.add_edge("n", END)
        result: dict[str, Any] = graph.compile().invoke(MiniState(case_id="c"))
        return result

    def test_unwrapped_node_can_write_a_wrong_type(self) -> None:
        """Unguarded, `flow_ratio` ends up holding a string its schema forbids."""
        final = self._run(lambda s: {"flow_ratio": "not-a-number"})
        assert final["flow_ratio"] == "not-a-number"

    def test_unwrapped_node_has_unknown_keys_dropped(self) -> None:
        final = self._run(lambda s: {"bogus": 123})
        assert "bogus" not in final

    def test_wrapper_rejects_a_wrong_type(self) -> None:
        def bad_node(state: MiniState) -> dict[str, Any]:
            return {"flow_ratio": "not-a-number"}

        with pytest.raises(NodeContractError, match="invalid update to MiniState"):
            self._run(validating_node(MiniState, bad_node))

    def test_wrapper_rejects_an_unknown_key(self) -> None:
        def bad_node(state: MiniState) -> dict[str, Any]:
            return {"bogus": 123}

        with pytest.raises(NodeContractError, match="bad_node"):
            self._run(validating_node(MiniState, bad_node))

    def test_wrapper_passes_valid_updates_through(self) -> None:
        def good_node(state: MiniState) -> dict[str, Any]:
            return {"flow_ratio": 0.5}

        assert self._run(validating_node(MiniState, good_node))["flow_ratio"] == 0.5

    def test_wrapper_allows_a_node_to_write_nothing(self) -> None:
        def noop_node(state: MiniState) -> None:
            return None

        assert self._run(validating_node(MiniState, noop_node))["flow_ratio"] == 1.0
