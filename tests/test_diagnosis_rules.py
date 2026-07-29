"""The rules baseline.

Two things are being protected here: that the baseline is *strong* (a weak control
arm would flatter every later ablation), and that it abstains rather than guesses
when the discriminating signal is gone.
"""

from __future__ import annotations

import random

from printpilot.diagnosis import diagnose
from printpilot.domain import FaultCode, RemediationClass, remediation_for
from printpilot.perception import perceive
from printpilot.simulator import (
    MATERIAL_SETPOINTS,
    Material,
    NoiseProfile,
    inject,
    sample,
)


def _diagnose(fault: FaultCode, seed: int = 1, dropped: tuple[str, ...] = ()) -> FaultCode:
    telemetry = sample(
        inject(fault, layer_count=60, material=Material.PLA, rng=random.Random(seed)),
        case_id="d1",
        noise=NoiseProfile.NOMINAL,
        rng=random.Random(seed),
        setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
        dropped_signals=dropped,
    )
    return diagnose(perceive(telemetry, material="PLA")).top.fault_code


class TestCorrectClassification:
    def test_full_clog(self) -> None:
        assert _diagnose(FaultCode.CLOG_FULL) is FaultCode.CLOG_FULL

    def test_partial_clog(self) -> None:
        assert _diagnose(FaultCode.CLOG_PARTIAL) is FaultCode.CLOG_PARTIAL

    def test_parameter_under_extrusion(self) -> None:
        assert _diagnose(FaultCode.UNDEREXT_PARAM) is FaultCode.UNDEREXT_PARAM

    def test_thermal_drift_is_not_absorbed_as_a_parameter_fault(self) -> None:
        """The precedence bug this test exists for: checking the flow branch before
        the thermal branch swallowed 15 of 20 thermal cases, because drifting off
        setpoint also depresses flow slightly."""
        assert _diagnose(FaultCode.THERMAL_DRIFT, seed=5) is FaultCode.THERMAL_DRIFT

    def test_recovered_dips_get_no_action(self) -> None:
        assert _diagnose(FaultCode.NORMAL_SUSPICIOUS, seed=2) is FaultCode.NORMAL_SUSPICIOUS


class TestAbstention:
    def test_abstains_when_the_discriminating_signal_is_missing(self) -> None:
        """Clog and parameter fault demand opposite responses; without the signal
        that tells them apart, guessing has an expected cost, not an expected value."""
        for fault in (FaultCode.CLOG_PARTIAL, FaultCode.UNDEREXT_PARAM):
            assert _diagnose(fault, dropped=("extruder_current",)) is FaultCode.UNKNOWN, (
                f"{fault} should abstain without extruder_current"
            )

    def test_abstains_without_any_flow_signal(self) -> None:
        assert _diagnose(FaultCode.CLOG_PARTIAL, dropped=("flow_ratio",)) is FaultCode.UNKNOWN

    def test_a_full_clog_is_still_caught_without_current(self) -> None:
        """Flow at zero is decisive on its own — abstaining here would be over-cautious."""
        assert _diagnose(FaultCode.CLOG_FULL, dropped=("extruder_current",)) is FaultCode.CLOG_FULL

    def test_healthy_prints_do_not_trigger_abstention(self) -> None:
        assert _diagnose(FaultCode.NORMAL_SUSPICIOUS, seed=9) is not FaultCode.UNKNOWN


class TestSafety:
    def test_no_clog_is_ever_routed_to_the_parameter_path(self) -> None:
        """The failure that matters: a clog classified as something the parameter
        path accepts would mean raising flow into a restricted nozzle."""
        param_path = {
            FaultCode.UNDEREXT_PARAM,
            FaultCode.THERMAL_DRIFT,
            FaultCode.NORMAL_SUSPICIOUS,
        }
        for fault in (FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL):
            for seed in range(25):
                assert _diagnose(fault, seed=seed) not in param_path

    def test_clog_predictions_never_carry_a_param_fixable_remediation(self) -> None:
        for fault in (FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL):
            predicted = _diagnose(fault, seed=3)
            assert remediation_for(predicted) is not RemediationClass.PARAM_FIXABLE


class TestEvidence:
    def test_every_concrete_diagnosis_cites_signals(self) -> None:
        telemetry = sample(
            inject(
                FaultCode.CLOG_PARTIAL,
                layer_count=60,
                material=Material.PLA,
                rng=random.Random(1),
            ),
            case_id="d2",
            noise=NoiseProfile.NOMINAL,
            rng=random.Random(1),
            setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
        )
        result = diagnose(perceive(telemetry, material="PLA"))
        assert result.top.evidence
        assert all(e.detail for e in result.top.evidence)
