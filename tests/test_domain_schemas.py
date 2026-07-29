"""Contract tests for the payloads nodes exchange.

Several of these encode defects found in the v1 plan review: a parameter delta
with no unit, and an action plan that carries a patch when the chosen action is
not "apply a patch". Both are now validation errors rather than review findings.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from printpilot.domain import (
    ActionPlan,
    ActionType,
    DiagnosisResult,
    EvidenceKind,
    EvidenceRef,
    FaultCode,
    Hypothesis,
    KnowledgePriority,
    ParamDelta,
    ParamName,
    ParamUnit,
    PhenomenonReport,
    RiskLevel,
    SafetyDecision,
    SafetyVerdict,
)


class TestParamDelta:
    def test_accepts_matching_unit(self) -> None:
        delta = ParamDelta(param=ParamName.NOZZLE_TEMP, delta=10.0, unit=ParamUnit.CELSIUS)
        assert delta.delta == pytest.approx(10.0)

    def test_rejects_mismatched_unit(self) -> None:
        with pytest.raises(ValidationError, match="measured in"):
            ParamDelta(param=ParamName.NOZZLE_TEMP, delta=10.0, unit=ParamUnit.MM)

    def test_unit_is_mandatory(self) -> None:
        """v1 wrote patches as the string "+10" with no unit attached."""
        with pytest.raises(ValidationError):
            ParamDelta.model_validate({"param": "nozzle_temp", "delta": 10.0})


class TestActionPlan:
    @staticmethod
    def _plan(**overrides: object) -> ActionPlan:
        base: dict[str, object] = {
            "case_id": "case-0001",
            "action_type": ActionType.PAUSE_AND_INSPECT,
            "rationale": "流量比下降且电流上升，先停机检查。",
            "rollback_plan": "恢复原参数并继续打印。",
        }
        base.update(overrides)
        return ActionPlan.model_validate(base)

    def test_non_patch_action_may_not_carry_a_patch(self) -> None:
        """A maintenance action must not smuggle parameter changes along with it."""
        with pytest.raises(ValidationError, match="must not carry a parameter patch"):
            self._plan(
                action_type=ActionType.MAINTENANCE_REQUIRED,
                patch=[ParamDelta(param=ParamName.FLOW, delta=5.0, unit=ParamUnit.PERCENT)],
            )

    def test_patch_action_requires_a_patch(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-empty patch"):
            self._plan(action_type=ActionType.APPLY_PARAM_PATCH)

    def test_rejects_duplicate_parameters(self) -> None:
        with pytest.raises(ValidationError, match="duplicate parameters"):
            self._plan(
                action_type=ActionType.APPLY_PARAM_PATCH,
                patch=[
                    ParamDelta(param=ParamName.FLOW, delta=5.0, unit=ParamUnit.PERCENT),
                    ParamDelta(param=ParamName.FLOW, delta=-2.0, unit=ParamUnit.PERCENT),
                ],
            )

    def test_valid_patch_plan(self) -> None:
        plan = self._plan(
            action_type=ActionType.APPLY_PARAM_PATCH,
            patch=[ParamDelta(param=ParamName.FLOW, delta=4.0, unit=ParamUnit.PERCENT)],
            risk_level=RiskLevel.LOW,
            requires_approval=False,
        )
        assert plan.action_type is ActionType.APPLY_PARAM_PATCH
        assert plan.patch[0].param is ParamName.FLOW

    def test_rejects_unknown_field(self) -> None:
        """extra="forbid" surfaces hallucinated keys at the boundary."""
        with pytest.raises(ValidationError):
            self._plan(confidence_score=0.9)


class TestHypothesis:
    def test_concrete_fault_requires_evidence(self) -> None:
        with pytest.raises(ValidationError, match="must cite at least one piece of evidence"):
            Hypothesis(
                fault_code=FaultCode.CLOG_FULL,
                confidence=0.9,
                reasoning="看起来像堵塞。",
            )

    def test_abstention_needs_no_evidence(self) -> None:
        hypothesis = Hypothesis(
            fault_code=FaultCode.UNKNOWN,
            confidence=0.4,
            reasoning="缺少挤出机电流信号，无法区分堵塞与参数性欠挤出。",
        )
        assert hypothesis.fault_code is FaultCode.UNKNOWN

    def test_confidence_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            Hypothesis(fault_code=FaultCode.UNKNOWN, confidence=1.4, reasoning="x")


class TestDiagnosisResult:
    def test_sorts_hypotheses_by_confidence(self, flow_evidence: EvidenceRef) -> None:
        result = DiagnosisResult(
            case_id="case-0001",
            hypotheses=[
                Hypothesis(
                    fault_code=FaultCode.UNDEREXT_PARAM,
                    confidence=0.31,
                    reasoning="流量略低。",
                    evidence=[flow_evidence],
                ),
                Hypothesis(
                    fault_code=FaultCode.CLOG_PARTIAL,
                    confidence=0.82,
                    reasoning="流量低且电流升高。",
                    evidence=[flow_evidence],
                ),
            ],
        )
        assert result.top.fault_code is FaultCode.CLOG_PARTIAL
        assert [h.confidence for h in result.hypotheses] == [0.82, 0.31]

    def test_abstained_reflects_top_hypothesis(self) -> None:
        result = DiagnosisResult(
            case_id="case-0002",
            hypotheses=[
                Hypothesis(fault_code=FaultCode.UNKNOWN, confidence=0.5, reasoning="证据不足。")
            ],
        )
        assert result.abstained is True

    def test_requires_at_least_one_hypothesis(self) -> None:
        with pytest.raises(ValidationError):
            DiagnosisResult(case_id="case-0003", hypotheses=[])


class TestEvidencePriority:
    def test_hard_rule_outranks_skill_outranks_rag_outranks_prior(self) -> None:
        order = [
            EvidenceRef(kind=EvidenceKind.LLM_PRIOR, ref="model"),
            EvidenceRef(kind=EvidenceKind.RAG, ref="chunk-7"),
            EvidenceRef(kind=EvidenceKind.SKILL, ref="extrusion-anomaly-triage"),
            EvidenceRef(kind=EvidenceKind.HARD_RULE, ref="SG-1"),
        ]
        priorities = [e.priority for e in order]
        assert priorities == sorted(priorities)
        assert order[-1].priority is KnowledgePriority.HARD_RULE


class TestSafetyVerdict:
    def test_block_must_name_a_rule(self) -> None:
        with pytest.raises(ValidationError, match="must name the rule"):
            SafetyVerdict(case_id="case-0001", decision=SafetyDecision.BLOCK)

    def test_allow_needs_no_rules(self) -> None:
        verdict = SafetyVerdict(case_id="case-0001", decision=SafetyDecision.ALLOW)
        assert verdict.violated_rules == []


class TestPhenomenonReport:
    def test_feature_lookup(self, clog_report: PhenomenonReport) -> None:
        found = clog_report.feature("flow_ratio_mean")
        assert found is not None
        assert found.exceeded is True
        assert clog_report.feature("nonexistent") is None

    def test_missing_signals_are_recorded_not_dropped(self, clog_report: PhenomenonReport) -> None:
        """Routing degrades confidence on missing inputs instead of filtering skills out."""
        assert "humidity" in clog_report.missing_signals
