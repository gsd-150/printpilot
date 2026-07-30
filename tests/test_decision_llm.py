"""LLM-backed decision: the arm that turns gate interception into a number.

The test that carries the design is
``test_the_gate_blocks_an_llm_patch_for_a_clog``: an LLM proposes a
perfectly well-formed parameter patch on a print with a mechanical
signature, and the round ends with the patch refused and nothing executed.
"""

from __future__ import annotations

import random

import pytest

from printpilot.decision.llm import LLMDecider, render_diagnosis
from printpilot.domain import (
    ActionPlan,
    ActionType,
    DiagnosisResult,
    EvidenceKind,
    EvidenceRef,
    FaultCode,
    Hypothesis,
    ParamDelta,
    ParamName,
    ParamUnit,
    PhenomenonReport,
    RiskLevel,
    SafetyDecision,
    SignalFeature,
)
from printpilot.llm import MockLLMClient
from printpilot.llm.base import LLMError
from printpilot.simulator import MATERIAL_SETPOINTS, Material, NoiseProfile, inject, sample
from printpilot.workflow import PipelineState, build_pipeline, run_pipeline

_SIGNAL = EvidenceRef(kind=EvidenceKind.SIGNAL, ref="flow_tail_mean")


def _diagnosis(fault: FaultCode = FaultCode.UNDEREXT_PARAM) -> DiagnosisResult:
    return DiagnosisResult(
        case_id="c-1",
        hypotheses=[
            Hypothesis(
                fault_code=fault,
                confidence=0.80,
                reasoning="尾段流量持续偏低。",
                evidence=[_SIGNAL],
            )
        ],
    )


def _report() -> PhenomenonReport:
    return PhenomenonReport(
        case_id="c-1",
        material="PLA",
        features=[
            SignalFeature(
                name="flow_tail_mean", value=0.81, unit="ratio", threshold=0.985, exceeded=True
            )
        ],
    )


def _patch_plan(case_id: str) -> ActionPlan:
    return ActionPlan(
        case_id=case_id,
        action_type=ActionType.APPLY_PARAM_PATCH,
        patch=[ParamDelta(param=ParamName.FLOW, delta=5.0, unit=ParamUnit.PERCENT)],
        rationale="流量偏低，小步提高 flow。",
        evidence_refs=[_SIGNAL],
        risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        rollback_plan="若无改善，回退 flow 5%。",
    )


class TestLLMDecider:
    def test_a_scripted_plan_flows_through_with_case_id_corrected(self) -> None:
        client = MockLLMClient(scripted=[_patch_plan("echoed-from-template")])
        plan = LLMDecider(client=client)(_diagnosis(), _report())

        assert plan.case_id == "c-1"
        assert plan.action_type is ActionType.APPLY_PARAM_PATCH
        assert client.calls[0].schema_name == "ActionPlan"

    def test_the_prompt_carries_the_diagnosis_and_the_features(self) -> None:
        client = MockLLMClient(scripted=[_patch_plan("c-1")])
        LLMDecider(client=client)(_diagnosis(), _report())

        prompt = client.calls[0].prompt
        assert "UNDEREXT_PARAM" in prompt
        assert "flow_tail_mean" in prompt
        assert "escalate_to_human" in prompt  # the way out is always offered

    def test_transport_failure_escalates_instead_of_guessing(self) -> None:
        decider = LLMDecider(client=MockLLMClient(raises=LLMError("outage")))
        plan = decider(_diagnosis(), _report())

        assert plan.action_type is ActionType.ESCALATE_TO_HUMAN
        assert plan.requires_approval
        assert "升级人工" in plan.rationale
        assert decider.failures == 1

    def test_render_diagnosis_shows_every_hypothesis(self) -> None:
        text = render_diagnosis(_diagnosis())
        assert "UNDEREXT_PARAM" in text
        assert "0.80" in text
        assert "flow_tail_mean" in text


class TestGateInterception:
    def test_the_gate_blocks_an_llm_patch_for_a_clog(self) -> None:
        """The claim "an LLM may propose but cannot release", measured live:
        the proposal is well-formed and self-consistent, and the interlock
        still refuses it on the mechanical signature."""
        profile = inject(
            FaultCode.CLOG_PARTIAL, layer_count=60, material=Material.PLA, rng=random.Random("g")
        )
        telemetry = sample(
            profile,
            case_id="g",
            noise=NoiseProfile.NOMINAL,
            rng=random.Random("g"),
            setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
        )
        setpoints = MATERIAL_SETPOINTS[Material.PLA]
        state = PipelineState(
            case_id="g",
            material=Material.PLA.value,
            current_params={
                ParamName.FLOW: 100.0,
                ParamName.NOZZLE_TEMP: setpoints["nozzle_temp"],
                ParamName.BED_TEMP: setpoints["bed_temp"],
            },
            telemetry=telemetry,
        )

        decider = LLMDecider(client=MockLLMClient(scripted=[_patch_plan("g")]))
        final = run_pipeline(state, graph=build_pipeline(decider=decider))

        assert final.plan is not None
        assert final.plan.action_type is ActionType.APPLY_PARAM_PATCH
        assert final.verdict is not None
        assert final.verdict.decision is not SafetyDecision.ALLOW
        assert final.execution is None, "an LLM-proposed patch for a clog must never execute"


class TestCli:
    def test_loop_with_llm_decider_refuses_when_unconfigured(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from printpilot.cli import EXIT_NOT_IMPLEMENTED, main

        assert main(["loop", "--decider", "llm"]) == EXIT_NOT_IMPLEMENTED
        captured = capsys.readouterr()
        assert "LLM 未配置" in captured.err
        assert "案例" not in captured.out
