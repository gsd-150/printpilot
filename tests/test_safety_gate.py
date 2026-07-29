"""The SafetyGate — the most important tests in the project.

Everything else measures how well the system diagnoses. These measure what happens
when it diagnoses *wrongly*, which on holdout it did for 10% of clogs.

The last class is the one that matters: it replays the diagnoses the model actually
produced on holdout and asserts the gate blocks the three clogs that reached the
parameter path. Not constructed failures — recorded ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printpilot.decision import decide
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
from printpilot.eval import load_record
from printpilot.perception import NOMINAL_BANDS, perceive
from printpilot.safety import INTERLOCK_CURRENT_RISE, GateContext, review
from printpilot.simulator import Split, load_cases, write_dataset

NOMINAL_PARAMS = {
    ParamName.FLOW: 100.0,
    ParamName.NOZZLE_TEMP: 205.0,
    ParamName.BED_TEMP: 60.0,
    ParamName.PRINT_SPEED: 60.0,
}

CLOGS = {FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL}


def _report(**values: float) -> PhenomenonReport:
    """Features default to nominal; named ones are overridden."""
    defaults = {name: 0.0 for name in NOMINAL_BANDS}
    defaults["flow_tail_mean"] = 1.0
    defaults["flow_min"] = 1.0
    defaults["current_mean"] = 0.35
    defaults.update(values)
    return PhenomenonReport(
        case_id="t-1",
        material="PLA",
        features=[
            SignalFeature(name=name, value=value, unit="ratio") for name, value in defaults.items()
        ],
    )


def _diagnosis(fault: FaultCode, confidence: float = 0.85) -> DiagnosisResult:
    evidence = (
        []
        if fault is FaultCode.UNKNOWN
        else [EvidenceRef(kind=EvidenceKind.SIGNAL, ref="flow_tail_mean")]
    )
    return DiagnosisResult(
        case_id="t-1",
        hypotheses=[
            Hypothesis(fault_code=fault, confidence=confidence, reasoning="t", evidence=evidence)
        ],
    )


def _patch_plan(**deltas: float) -> ActionPlan:
    return ActionPlan(
        case_id="t-1",
        action_type=ActionType.APPLY_PARAM_PATCH,
        patch=[
            ParamDelta(
                param=ParamName(name),
                delta=value,
                unit=ParamUnit.PERCENT if name == "flow" else ParamUnit.CELSIUS,
            )
            for name, value in deltas.items()
        ],
        rationale="t",
        rollback_plan="t",
        requires_approval=False,
    )


def _verdict(
    plan: ActionPlan,
    diagnosis: DiagnosisResult,
    report: PhenomenonReport,
    params: dict[ParamName, float] | None = None,
) -> object:
    return review(
        GateContext(
            plan=plan,
            diagnosis=diagnosis,
            report=report,
            current_params=params or dict(NOMINAL_PARAMS),
            material="PLA",
        )
    )


class TestLabelConsistency:
    """SG-1/SG-2: the action must be one the diagnosed fault admits."""

    @pytest.mark.parametrize("fault", sorted(CLOGS))
    def test_a_diagnosed_clog_cannot_take_the_parameter_path(self, fault: FaultCode) -> None:
        verdict = _verdict(_patch_plan(flow=5.0), _diagnosis(fault), _report())
        assert verdict.decision is SafetyDecision.BLOCK  # type: ignore[attr-defined]
        assert any("SG-1" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_a_partial_clog_may_not_have_its_flow_raised(self) -> None:
        verdict = _verdict(_patch_plan(flow=5.0), _diagnosis(FaultCode.CLOG_PARTIAL), _report())
        assert any("SG-2" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_a_parameter_fault_may_take_the_parameter_path(self) -> None:
        verdict = _verdict(_patch_plan(flow=5.0), _diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        assert verdict.decision is SafetyDecision.ALLOW  # type: ignore[attr-defined]

    def test_an_abstention_is_not_a_mandate(self) -> None:
        verdict = _verdict(_patch_plan(flow=5.0), _diagnosis(FaultCode.UNKNOWN, 0.4), _report())
        assert any("SG-5" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]


class TestHardwareBounds:
    """SG-3: applied to the resulting value, not only the step."""

    def test_an_oversized_step_is_refused(self) -> None:
        verdict = _verdict(_patch_plan(flow=40.0), _diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        assert any("SG-3" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_a_small_step_off_an_already_high_value_is_refused(self) -> None:
        """The step is legal; the destination is not."""
        verdict = _verdict(
            _patch_plan(flow=8.0),
            _diagnosis(FaultCode.UNDEREXT_PARAM),
            _report(),
            params={**NOMINAL_PARAMS, ParamName.FLOW: 118.0},
        )
        assert any("超出硬件边界" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_an_unknown_current_value_is_refused_not_assumed(self) -> None:
        verdict = _verdict(
            _patch_plan(flow=5.0),
            _diagnosis(FaultCode.UNDEREXT_PARAM),
            _report(),
            params={ParamName.NOZZLE_TEMP: 205.0},
        )
        assert any("缺少" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]


class TestConfidenceGate:
    """SG-4: autonomy is earned."""

    def test_low_confidence_escalates(self) -> None:
        verdict = _verdict(
            _patch_plan(flow=5.0), _diagnosis(FaultCode.UNDEREXT_PARAM, 0.4), _report()
        )
        assert verdict.decision is SafetyDecision.ESCALATE  # type: ignore[attr-defined]

    def test_a_high_risk_plan_must_declare_it_needs_approval(self) -> None:
        plan = _patch_plan(flow=5.0).model_copy(
            update={"risk_level": RiskLevel.HIGH, "requires_approval": False}
        )
        verdict = _verdict(plan, _diagnosis(FaultCode.UNDEREXT_PARAM), _report())
        assert verdict.decision is SafetyDecision.ESCALATE  # type: ignore[attr-defined]


class TestEvidenceInterlock:
    """SG-6: the rule that does not read the diagnosis.

    This is what separates the gate from a consistency check. A misdiagnosed clog
    produces a plan that agrees with its own diagnosis; only a rule reading the raw
    features can refuse it.
    """

    def test_a_misdiagnosed_clog_is_blocked_by_the_signals(self) -> None:
        """Diagnosis says parameter fault, plan agrees with it, current says clog."""
        verdict = _verdict(
            _patch_plan(flow=5.0),
            _diagnosis(FaultCode.UNDEREXT_PARAM),
            _report(current_delta=0.09, flow_tail_mean=0.82),
        )
        assert verdict.decision is SafetyDecision.BLOCK  # type: ignore[attr-defined]
        assert any("SG-6" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_the_interlock_trips_before_the_diagnoser_would_call_a_clog(self) -> None:
        """A false trip costs a pause; a missed one costs a nozzle."""
        from printpilot.diagnosis.rules import CURRENT_RISE_THRESHOLD

        assert INTERLOCK_CURRENT_RISE < CURRENT_RISE_THRESHOLD

    def test_collapsed_flow_blocks_any_patch(self) -> None:
        verdict = _verdict(
            _patch_plan(flow=5.0),
            _diagnosis(FaultCode.UNDEREXT_PARAM),
            _report(flow_tail_mean=0.05),
        )
        assert any("SG-6" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_a_missing_discriminating_signal_blocks_a_patch(self) -> None:
        report = _report(flow_tail_mean=0.85).model_copy(
            update={"uncomputable_features": ["current_delta", "current_mean"]}
        )
        verdict = _verdict(_patch_plan(flow=5.0), _diagnosis(FaultCode.UNDEREXT_PARAM), report)
        assert any("SG-6" in r for r in verdict.violated_rules)  # type: ignore[attr-defined]

    def test_a_genuinely_normal_case_still_passes(self) -> None:
        """An interlock that never lets anything through is not a gate."""
        verdict = _verdict(
            _patch_plan(flow=5.0),
            _diagnosis(FaultCode.UNDEREXT_PARAM),
            _report(current_delta=0.001, flow_tail_mean=0.88),
        )
        assert verdict.decision is SafetyDecision.ALLOW  # type: ignore[attr-defined]


class TestRecordedFailuresAreBlocked:
    """Replay of the diagnoses the model actually produced on holdout.

    ``llm+skills`` sent 10% of clogs down the parameter path there. These are those
    cases, not constructed ones — the strongest available evidence that the gate
    addresses a real failure rather than an imagined one.
    """

    @pytest.fixture(scope="class")
    def holdout_cases(self, tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
        root = tmp_path_factory.mktemp("gate")
        write_dataset(root, master_seed=42)
        return {c.case_id: c for c in load_cases(root, Split.HOLDOUT)}

    def test_every_recorded_misroute_is_refused(self, holdout_cases: dict[str, object]) -> None:
        record = load_record(Path("evals/runs/holdout-skills.json"))
        reached_parameter_path = 0
        blocked_clogs = 0

        for prediction in record.predictions:
            case = holdout_cases[prediction.case_id]
            report = perceive(case.telemetry, material=case.material.value)  # type: ignore[attr-defined]
            diagnosis = _diagnosis(prediction.predicted, prediction.confidence).model_copy(
                update={"case_id": prediction.case_id}
            )
            plan = decide(diagnosis, report).model_copy(update={"case_id": prediction.case_id})
            if plan.action_type is not ActionType.APPLY_PARAM_PATCH:
                continue

            verdict = review(
                GateContext(
                    plan=plan,
                    diagnosis=diagnosis,
                    report=report,
                    current_params={
                        ParamName.FLOW: 100.0,
                        ParamName.NOZZLE_TEMP: case.telemetry.setpoints["nozzle_temp"],  # type: ignore[attr-defined]
                        ParamName.BED_TEMP: case.telemetry.setpoints["bed_temp"],  # type: ignore[attr-defined]
                    },
                    material=case.material.value,  # type: ignore[attr-defined]
                )
            )
            if prediction.truth in CLOGS:
                if verdict.decision is SafetyDecision.ALLOW:
                    reached_parameter_path += 1
                else:
                    blocked_clogs += 1

        assert blocked_clogs >= 3, "the recorded misroutes should reach the gate"
        assert reached_parameter_path == 0, (
            f"{reached_parameter_path} recorded clog(s) still reached the parameter path"
        )
