"""Properties of the synthetic environment.

The most important tests here are the ones about *difficulty*. A generator whose
fault classes are trivially separable produces impressive numbers that mean
nothing, and the first version of this simulator had exactly that defect: the
residual-flow bands for the two confusable faults did not overlap, so a single
threshold on flow ratio separated them perfectly. These tests pin the overlap so
it cannot quietly come back.
"""

from __future__ import annotations

import random
from statistics import mean

import pytest

from printpilot.domain import FaultCode, RemediationClass
from printpilot.simulator import (
    CONFUSABLE_PAIR,
    DISCRIMINATING_SIGNAL,
    INJECTABLE_FAULTS,
    MATERIAL_SETPOINTS,
    InjectionProfile,
    Material,
    NoiseProfile,
    Split,
    Telemetry,
    build_split_plan,
    evaluate_quality,
    generate,
    inject,
    sample,
    split_sizes,
)
from printpilot.simulator.virtual_sensors import SIGNAL_NAMES

LAYERS = 60


def _profile(fault: FaultCode, seed: int, material: Material = Material.PLA) -> InjectionProfile:
    return inject(fault, layer_count=LAYERS, material=material, rng=random.Random(seed))


def _tail(values: list[float]) -> float:
    return mean(values[int(len(values) * 0.75) :])


class TestDifficulty:
    """Without these properties the benchmark measures a threshold, not a diagnosis."""

    def test_confusable_pair_overlaps_on_flow_ratio(self) -> None:
        clog = [_tail(_profile(FaultCode.CLOG_PARTIAL, s).flow_ratio) for s in range(60)]
        param = [_tail(_profile(FaultCode.UNDEREXT_PARAM, s).flow_ratio) for s in range(60)]

        overlap_lo = max(min(clog), min(param))
        overlap_hi = min(max(clog), max(param))
        assert overlap_hi > overlap_lo, "flow ratio alone must not separate the pair"
        assert overlap_hi - overlap_lo > 0.05, "the ambiguous region is too narrow to matter"

    def test_extruder_current_moves_in_opposite_directions(self) -> None:
        """A restriction raises the force needed; a low flow setting lowers it slightly."""
        clog = [_tail(_profile(FaultCode.CLOG_PARTIAL, s).extruder_current) for s in range(40)]
        param = [_tail(_profile(FaultCode.UNDEREXT_PARAM, s).extruder_current) for s in range(40)]
        assert min(clog) > max(param), "current must carry the decision the flow curve cannot"

    def test_clog_current_gain_varies_between_cases(self) -> None:
        """With one fixed gain, current would be an exact function of flow and a rule
        could invert it. Diagnosis has to stay statistical."""
        ratios = []
        for seed in range(40):
            p = _profile(FaultCode.CLOG_PARTIAL, seed)
            deficit = 1.0 - _tail(p.flow_ratio)
            if deficit > 0.05:
                ratios.append((_tail(p.extruder_current) - 0.35) / deficit)
        assert max(ratios) - min(ratios) > 0.1

    def test_transient_dips_are_not_sustained(self) -> None:
        """NORMAL_SUSPICIOUS dips as deep as a mild clog but briefly — separating the
        two requires looking at duration, not depth."""
        for seed in range(30):
            flow = _profile(FaultCode.NORMAL_SUSPICIOUS, seed).flow_ratio
            assert min(flow) < 0.95, "a trap with no dip traps nothing"
            dipped = sum(1 for v in flow if v < 0.97) / len(flow)
            assert dipped < 0.15, "a dip covering much of the print is not transient"

    def test_dips_recover_within_the_trace(self) -> None:
        """A dip in the final layers is indistinguishable from a clog beginning, so
        scoring it as 'normal' would be marking an unanswerable case."""
        for seed in range(30):
            flow = _profile(FaultCode.NORMAL_SUSPICIOUS, seed).flow_ratio
            assert _tail(flow) > 0.98, "recovery must be observable inside the trace"


class TestInjection:
    @pytest.mark.parametrize("fault", INJECTABLE_FAULTS)
    def test_every_injectable_fault_produces_full_length_traces(self, fault: FaultCode) -> None:
        profile = _profile(fault, 1)
        assert len(profile.flow_ratio) == LAYERS
        assert len(profile.extruder_current) == LAYERS
        assert len(profile.hotend_temp) == LAYERS
        assert len(profile.hotend_duty) == LAYERS

    def test_full_clog_collapses_flow(self) -> None:
        assert _tail(_profile(FaultCode.CLOG_FULL, 3).flow_ratio) < 0.15

    def test_thermal_drift_moves_temperature_off_setpoint(self) -> None:
        profile = _profile(FaultCode.THERMAL_DRIFT, 5)
        setpoint = MATERIAL_SETPOINTS[Material.PLA]["nozzle_temp"]
        assert abs(_tail(profile.hotend_temp) - setpoint) > 5.0

    def test_thermal_drift_barely_touches_flow(self) -> None:
        """It is a temperature fault. If it also tanked flow it would be a second
        clog class wearing a different label."""
        assert _tail(_profile(FaultCode.THERMAL_DRIFT, 7).flow_ratio) > 0.9

    def test_unknown_is_not_injectable(self) -> None:
        with pytest.raises(ValueError, match="not injectable"):
            _profile(FaultCode.UNKNOWN, 1)

    def test_injection_is_deterministic_for_a_seed(self) -> None:
        assert _profile(FaultCode.CLOG_PARTIAL, 11) == _profile(FaultCode.CLOG_PARTIAL, 11)


class TestVirtualSensors:
    def _sample(self, dropped: tuple[str, ...] = ()) -> Telemetry:
        return sample(
            _profile(FaultCode.CLOG_PARTIAL, 2),
            case_id="c1",
            noise=NoiseProfile.NOMINAL,
            rng=random.Random(2),
            setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
            dropped_signals=dropped,
        )

    def test_all_signals_present_by_default(self) -> None:
        telemetry = self._sample()
        assert telemetry.available_signals == sorted(SIGNAL_NAMES)
        assert telemetry.missing_signals == []

    def test_dropped_signal_is_absent_not_null(self) -> None:
        """Absent rather than NaN, so downstream code must handle it deliberately."""
        telemetry = self._sample(dropped=(DISCRIMINATING_SIGNAL,))
        assert DISCRIMINATING_SIGNAL not in telemetry.signals
        assert telemetry.missing_signals == [DISCRIMINATING_SIGNAL]

    def test_dropping_an_unknown_signal_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="unknown signal"):
            self._sample(dropped=("no_such_sensor",))

    def test_noise_is_applied(self) -> None:
        telemetry = self._sample()
        clean = _profile(FaultCode.CLOG_PARTIAL, 2).flow_ratio
        assert telemetry.signals["flow_ratio"] != clean


class TestQualityEvaluator:
    """Independence is the point: this must not be able to see a fault label."""

    def _quality(self, fault: FaultCode, seed: int = 4) -> float:
        telemetry = sample(
            _profile(fault, seed),
            case_id="q",
            noise=NoiseProfile.LOW,
            rng=random.Random(seed),
            setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
        )
        return evaluate_quality(telemetry).score

    def test_takes_telemetry_only(self) -> None:
        import inspect

        params = set(inspect.signature(evaluate_quality).parameters)
        assert params == {"telemetry"}, "no parameter may carry ground truth into scoring"

    def test_full_clog_scores_worst(self) -> None:
        scores = {f: self._quality(f) for f in INJECTABLE_FAULTS}
        assert scores[FaultCode.CLOG_FULL] == min(scores.values())

    def test_transient_dips_score_near_nominal(self) -> None:
        assert self._quality(FaultCode.NORMAL_SUSPICIOUS) > 0.8

    def test_survives_a_missing_temperature_signal(self) -> None:
        """Sensor dropout must not crash scoring; the thermal term simply drops out."""
        telemetry = sample(
            _profile(FaultCode.THERMAL_DRIFT, 8),
            case_id="q3",
            noise=NoiseProfile.LOW,
            rng=random.Random(8),
            setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
            dropped_signals=("hotend_temp",),
        )
        report = evaluate_quality(telemetry)
        assert report.thermal_excursion == 0.0
        assert report.score > 0.0

    def test_works_without_the_discriminating_signal(self) -> None:
        """Quality is about outcome; the diagnostic signal is irrelevant to it."""
        telemetry = sample(
            _profile(FaultCode.CLOG_PARTIAL, 6),
            case_id="q2",
            noise=NoiseProfile.LOW,
            rng=random.Random(6),
            setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
            dropped_signals=(DISCRIMINATING_SIGNAL,),
        )
        assert 0.0 <= evaluate_quality(telemetry).score <= 1.0

    def test_thermal_excursion_lowers_the_score(self) -> None:
        assert self._quality(FaultCode.THERMAL_DRIFT) < self._quality(FaultCode.NORMAL_SUSPICIOUS)


class TestSplitPlan:
    def test_sizes_match_the_plan(self) -> None:
        assert split_sizes() == {Split.DEV: 100, Split.HOLDOUT: 30, Split.CHALLENGE: 30}

    def test_families_are_disjoint_across_splits(self) -> None:
        plan = build_split_plan()
        ids = {split: {p.family.family_id for p in plans} for split, plans in plan.items()}
        assert not ids[Split.DEV] & ids[Split.HOLDOUT]
        assert not ids[Split.DEV] & ids[Split.CHALLENGE]
        assert not ids[Split.HOLDOUT] & ids[Split.CHALLENGE]

    def test_dev_and_holdout_share_no_material_geometry_combination(self) -> None:
        plan = build_split_plan()
        combos = {
            split: {(p.family.material, p.family.geometry) for p in plans}
            for split, plans in plan.items()
        }
        assert not combos[Split.DEV] & combos[Split.HOLDOUT]

    def test_tpu_appears_only_in_challenge(self) -> None:
        plan = build_split_plan()
        for split in (Split.DEV, Split.HOLDOUT):
            assert all(p.family.material is not Material.TPU for p in plan[split])
        assert any(p.family.material is Material.TPU for p in plan[Split.CHALLENGE])

    def test_boundary_noise_appears_only_in_challenge(self) -> None:
        plan = build_split_plan()
        for split in (Split.DEV, Split.HOLDOUT):
            assert all(p.family.noise is not NoiseProfile.BOUNDARY for p in plan[split])
        assert any(p.family.noise is NoiseProfile.BOUNDARY for p in plan[Split.CHALLENGE])

    def test_challenge_removes_the_discriminating_signal_for_the_confusable_pair(
        self,
    ) -> None:
        """Without it the honest answer is UNKNOWN, so this sub-group is what makes
        the abstention path measurable."""
        blinded = [
            p
            for p in build_split_plan()[Split.CHALLENGE]
            if DISCRIMINATING_SIGNAL in p.family.dropped_signals
        ]
        assert {p.family.fault for p in blinded} == set(CONFUSABLE_PAIR)

    def test_every_split_contains_the_do_nothing_class(self) -> None:
        plan = build_split_plan()
        for split, plans in plan.items():
            faults = {p.family.fault for p in plans}
            assert FaultCode.NORMAL_SUSPICIOUS in faults, f"{split} has no negatives"


class TestGeneration:
    def test_case_and_label_ids_line_up(self) -> None:
        for rows in generate(master_seed=7).values():
            for case, label in rows:
                assert case.case_id == label.case_id
                assert case.family_id == label.family_id

    def test_labels_carry_the_remediation_class(self) -> None:
        rows = generate(master_seed=7)[Split.HOLDOUT]
        by_fault = {label.fault_codes[0]: label.remediation for _, label in rows}
        assert by_fault[FaultCode.CLOG_FULL] is RemediationClass.ABORT
        assert by_fault[FaultCode.CLOG_PARTIAL] is RemediationClass.MAINTENANCE
        assert by_fault[FaultCode.UNDEREXT_PARAM] is RemediationClass.PARAM_FIXABLE
        assert by_fault[FaultCode.NORMAL_SUSPICIOUS] is RemediationClass.NO_ACTION

    def test_same_seed_reproduces_identical_cases(self) -> None:
        a = generate(master_seed=13)[Split.HOLDOUT]
        b = generate(master_seed=13)[Split.HOLDOUT]
        assert [c.model_dump_json() for c, _ in a] == [c.model_dump_json() for c, _ in b]

    def test_different_seeds_produce_different_cases(self) -> None:
        a = generate(master_seed=13)[Split.HOLDOUT]
        b = generate(master_seed=14)[Split.HOLDOUT]
        assert [c.model_dump_json() for c, _ in a] != [c.model_dump_json() for c, _ in b]
