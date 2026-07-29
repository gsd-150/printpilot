"""The closed loop.

The test that carries the design is ``test_patching_a_clog_makes_it_worse``. It
does not exercise the pipeline at all — it checks the *simulator*, because if
raising flow into a restriction produced no change rather than harm, then the loop
could never distinguish a wrong action from a useless one, and the SafetyGate's
value would be unmeasurable.
"""

from __future__ import annotations

import random

import pytest

from printpilot.domain import ActionType, FaultCode, SafetyDecision
from printpilot.loop import LoopOutcome, demo_families, run_round
from printpilot.simulator import (
    MATERIAL_SETPOINTS,
    Material,
    NoiseProfile,
    ScenarioFamily,
    evaluate_quality,
    inject,
    sample,
)
from printpilot.simulator.fault_injection import PrintParams
from printpilot.simulator.scenario import Geometry

SEEDS = [f"s{i}" for i in range(12)]


def _family(fault: FaultCode) -> ScenarioFamily:
    return ScenarioFamily(
        fault=fault,
        material=Material.PLA,
        geometry=Geometry.BOX,
        noise=NoiseProfile.NOMINAL,
    )


def _quality_under(fault: FaultCode, params: PrintParams, seed: str = "h") -> float:
    profile = inject(
        fault, layer_count=60, material=Material.PLA, rng=random.Random(seed), params=params
    )
    telemetry = sample(
        profile,
        case_id="h",
        noise=NoiseProfile.LOW,
        rng=random.Random(seed),
        setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
    )
    return evaluate_quality(telemetry).score


class TestSimulatorRespondsToSettings:
    """Without this the loop measures nothing."""

    def test_raising_flow_fixes_a_parameter_under_extrusion(self) -> None:
        before = _quality_under(FaultCode.UNDEREXT_PARAM, PrintParams())
        after = _quality_under(FaultCode.UNDEREXT_PARAM, PrintParams(flow_percent=105.0))
        assert after > before

    def test_patching_a_clog_makes_it_worse(self) -> None:
        """The restriction limits output, so commanding more flow does not increase
        what comes out — it increases the force pushing against the blockage.

        If this produced *no change* instead of harm, a wrong action and a useless
        one would look identical, and there would be nothing for the gate to be
        worth preventing.
        """
        base = inject(
            FaultCode.CLOG_PARTIAL,
            layer_count=60,
            material=Material.PLA,
            rng=random.Random("h"),
            params=PrintParams(),
        )
        pushed = inject(
            FaultCode.CLOG_PARTIAL,
            layer_count=60,
            material=Material.PLA,
            rng=random.Random("h"),
            params=PrintParams(flow_percent=110.0),
        )
        assert pushed.flow_ratio == base.flow_ratio, "the restriction, not the setting, limits it"
        assert max(pushed.extruder_current) > max(base.extruder_current), "force must rise"

    def test_a_setpoint_offset_moves_measured_temperature(self) -> None:
        before = _quality_under(FaultCode.THERMAL_DRIFT, PrintParams())
        worse = _quality_under(FaultCode.THERMAL_DRIFT, PrintParams(nozzle_temp_offset=15.0))
        better = _quality_under(FaultCode.THERMAL_DRIFT, PrintParams(nozzle_temp_offset=-15.0))
        assert {before, worse, better} != {before}, "the offset must do something"

    def test_default_params_reproduce_the_unpatched_traces(self) -> None:
        """Adding the parameter must not have changed the published dataset."""
        plain = inject(
            FaultCode.CLOG_PARTIAL, layer_count=60, material=Material.PLA, rng=random.Random(7)
        )
        explicit = inject(
            FaultCode.CLOG_PARTIAL,
            layer_count=60,
            material=Material.PLA,
            rng=random.Random(7),
            params=PrintParams(),
        )
        assert plain == explicit


class TestLoopOutcomes:
    def test_a_parameter_fault_is_actually_fixed(self) -> None:
        improved = sum(
            run_round(_family(FaultCode.UNDEREXT_PARAM), case_id="c", seed=s).outcome
            is LoopOutcome.IMPROVED
            for s in SEEDS
        )
        assert improved >= len(SEEDS) * 0.7, f"only {improved}/{len(SEEDS)} improved"

    @pytest.mark.parametrize("fault", [FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL])
    def test_no_clog_ever_reaches_a_parameter_patch(self, fault: FaultCode) -> None:
        for seed in SEEDS:
            result = run_round(_family(fault), case_id="c", seed=seed)
            assert result.plan.action_type is not ActionType.APPLY_PARAM_PATCH
            assert result.outcome is not LoopOutcome.HARMED

    def test_a_healthy_print_is_never_harmed(self) -> None:
        """Intervening on a good print is the loop's own false-positive cost.

        It is not zero: the diagnoser occasionally calls a recovered transient a
        parameter fault, and the gate correctly allows the patch — there is no
        mechanical signature to trip on, because there is no mechanical problem.
        The requirement is therefore that such interventions do no damage, and
        that they stay rare, not that they never happen.
        """
        results = [
            run_round(_family(FaultCode.NORMAL_SUSPICIOUS), case_id="c", seed=seed)
            for seed in SEEDS
        ]
        assert all(r.outcome is not LoopOutcome.HARMED for r in results)

        unnecessary = [r for r in results if r.outcome is not LoopOutcome.NO_ACTION]
        assert len(unnecessary) <= len(SEEDS) * 0.2, (
            f"{len(unnecessary)}/{len(SEEDS)} healthy prints were acted on"
        )

    def test_thermal_correction_helps_more_often_than_it_hurts(self) -> None:
        """Regression on the signed-bias fix: with only the absolute deviation
        available the correction always pushed down, so half the cases got worse."""
        outcomes = [
            run_round(_family(FaultCode.THERMAL_DRIFT), case_id="c", seed=s).outcome for s in SEEDS
        ]
        assert outcomes.count(LoopOutcome.HARMED) == 0

    def test_the_loop_is_deterministic(self) -> None:
        a = run_round(_family(FaultCode.UNDEREXT_PARAM), case_id="c", seed="fixed")
        b = run_round(_family(FaultCode.UNDEREXT_PARAM), case_id="c", seed="fixed")
        assert a.delta == b.delta
        assert a.outcome is b.outcome

    def test_every_round_records_the_gate_verdict(self) -> None:
        for family in demo_families():
            result = run_round(family, case_id="c", seed="demo")
            assert result.verdict.decision in set(SafetyDecision)
            assert result.summary()

    def test_quality_is_judged_without_knowing_the_fault(self) -> None:
        """The independence that makes 'did it help?' worth asking."""
        import inspect

        assert set(inspect.signature(evaluate_quality).parameters) == {"telemetry"}
