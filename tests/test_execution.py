"""Decision and execution.

The invariant: nothing changes a parameter except :class:`Executor`, and it will
not act on a plan the gate did not allow. It re-checks the verdict itself rather
than trusting the caller — "review then apply" is easy to get wrong once there are
branches, and a skipped review does not announce itself.
"""

from __future__ import annotations

import pytest

from printpilot.decision import FLOW_STEP, decide
from printpilot.domain import (
    HARDWARE_BOUNDS,
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
    RemediationClass,
    SafetyDecision,
    SafetyVerdict,
    SignalFeature,
    remediation_for,
)
from printpilot.execution import ExecutionRefusedError, Executor

START = {ParamName.FLOW: 100.0, ParamName.NOZZLE_TEMP: 205.0}


def _report(**values: float) -> PhenomenonReport:
    return PhenomenonReport(
        case_id="t-1",
        material="PLA",
        features=[
            SignalFeature(name=name, value=value, unit="ratio")
            for name, value in ({"flow_tail_mean": 0.9, **values}).items()
        ],
    )


def _diagnosis(fault: FaultCode) -> DiagnosisResult:
    evidence = (
        []
        if fault is FaultCode.UNKNOWN
        else [EvidenceRef(kind=EvidenceKind.SIGNAL, ref="flow_tail_mean")]
    )
    return DiagnosisResult(
        case_id="t-1",
        hypotheses=[
            Hypothesis(fault_code=fault, confidence=0.85, reasoning="t", evidence=evidence)
        ],
    )


def _allow() -> SafetyVerdict:
    return SafetyVerdict(case_id="t-1", decision=SafetyDecision.ALLOW)


class TestDecision:
    @pytest.mark.parametrize(
        ("fault", "expected"),
        [
            (FaultCode.CLOG_FULL, ActionType.ABORT_PRINT),
            (FaultCode.CLOG_PARTIAL, ActionType.PAUSE_AND_INSPECT),
            (FaultCode.UNDEREXT_PARAM, ActionType.APPLY_PARAM_PATCH),
            (FaultCode.THERMAL_DRIFT, ActionType.APPLY_PARAM_PATCH),
            (FaultCode.NORMAL_SUSPICIOUS, ActionType.NO_ACTION),
            (FaultCode.UNKNOWN, ActionType.ESCALATE_TO_HUMAN),
        ],
    )
    def test_each_fault_maps_to_its_action(self, fault: FaultCode, expected: ActionType) -> None:
        assert decide(_diagnosis(fault), _report()).action_type is expected

    def test_no_clog_ever_yields_a_parameter_patch(self) -> None:
        for fault in (FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL):
            assert remediation_for(fault) is not RemediationClass.PARAM_FIXABLE
            assert decide(_diagnosis(fault), _report()).action_type is not (
                ActionType.APPLY_PARAM_PATCH
            )

    def test_patches_stay_within_the_single_step_limit(self) -> None:
        """A patch that fixes the problem in one jump also breaks it in one jump
        if the diagnosis was wrong."""
        for fault in (FaultCode.UNDEREXT_PARAM, FaultCode.THERMAL_DRIFT):
            for delta in decide(_diagnosis(fault), _report()).patch:
                assert abs(delta.delta) <= HARDWARE_BOUNDS[delta.param].max_abs_delta

    def test_thermal_correction_opposes_the_drift_in_both_directions(self) -> None:
        """The bug this replaces: the decision read the *absolute* deviation, which
        is always positive, so the correction was always downward — wrong on every
        case where the hot end was running cold, which is half of them."""
        hot = decide(
            _diagnosis(FaultCode.THERMAL_DRIFT),
            _report(temp_deviation_tail=0.06, temp_bias_tail=0.06),
        )
        cold = decide(
            _diagnosis(FaultCode.THERMAL_DRIFT),
            _report(temp_deviation_tail=0.06, temp_bias_tail=-0.06),
        )
        assert hot.patch[0].delta < 0
        assert cold.patch[0].delta > 0

    def test_every_plan_carries_a_rollback(self) -> None:
        for fault in FaultCode:
            assert decide(_diagnosis(fault), _report()).rollback_plan.strip()


class TestExecution:
    def test_applies_an_allowed_patch(self) -> None:
        plan = decide(_diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        result = Executor().apply(plan, _allow(), START)
        assert result.applied
        assert result.params[ParamName.FLOW] == pytest.approx(100.0 + FLOW_STEP)

    def test_refuses_a_blocked_plan(self) -> None:
        """The check is here, not only in the caller."""
        blocked = SafetyVerdict(
            case_id="t-1",
            decision=SafetyDecision.BLOCK,
            violated_rules=["SG-6: 机械阻力迹象"],
        )
        plan = decide(_diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        with pytest.raises(ExecutionRefusedError, match="SG-6"):
            Executor().apply(plan, blocked, START)

    def test_refuses_an_escalated_plan(self) -> None:
        escalated = SafetyVerdict(case_id="t-1", decision=SafetyDecision.ESCALATE)
        plan = decide(_diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        with pytest.raises(ExecutionRefusedError):
            Executor().apply(plan, escalated, START)

    def test_a_non_patch_action_changes_nothing(self) -> None:
        plan = decide(_diagnosis(FaultCode.CLOG_PARTIAL), _report())
        result = Executor().apply(plan, _allow(), START)
        assert not result.applied
        assert result.params == START

    def test_rollback_restores_exactly(self) -> None:
        plan = decide(_diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        result = Executor().apply(plan, _allow(), START)
        assert result.rollback() == START

    def test_rollback_is_exact_even_for_a_clamped_delta(self) -> None:
        """Derived from recorded before-values, not by re-subtracting the delta."""
        plan = ActionPlan(
            case_id="t-1",
            action_type=ActionType.APPLY_PARAM_PATCH,
            patch=[ParamDelta(param=ParamName.FLOW, delta=3.0, unit=ParamUnit.PERCENT)],
            rationale="t",
            rollback_plan="t",
        )
        result = Executor().apply(plan, _allow(), {ParamName.FLOW: 97.5})
        assert result.rollback()[ParamName.FLOW] == pytest.approx(97.5)

    def test_the_diff_is_readable(self) -> None:
        plan = decide(_diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        assert "flow: 100 -> 105" in Executor().apply(plan, _allow(), START).diff

    def test_history_records_every_attempt(self) -> None:
        executor = Executor()
        executor.apply(decide(_diagnosis(FaultCode.UNDEREXT_PARAM), _report()), _allow(), START)
        executor.apply(decide(_diagnosis(FaultCode.NORMAL_SUSPICIOUS), _report()), _allow(), START)
        assert len(executor.history) == 2
