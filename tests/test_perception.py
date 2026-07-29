"""Perception measures; it does not judge."""

from __future__ import annotations

import random

from printpilot.domain import FaultCode, PhenomenonReport
from printpilot.perception import NOMINAL_BANDS, Band, perceive
from printpilot.simulator import (
    MATERIAL_SETPOINTS,
    Material,
    NoiseProfile,
    Telemetry,
    inject,
    sample,
)


def _telemetry(fault: FaultCode, seed: int = 1, dropped: tuple[str, ...] = ()) -> Telemetry:
    return sample(
        inject(fault, layer_count=60, material=Material.PLA, rng=random.Random(seed)),
        case_id="p1",
        noise=NoiseProfile.NOMINAL,
        rng=random.Random(seed),
        setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
        dropped_signals=dropped,
    )


def _report(fault: FaultCode, **kwargs: object) -> PhenomenonReport:
    telemetry = _telemetry(fault, **kwargs)  # type: ignore[arg-type]
    return perceive(telemetry, material="PLA")


class TestNoLeakage:
    def test_report_has_no_family_field(self) -> None:
        """family_id encodes the injected fault; it must not be representable here."""
        assert "scenario_family" not in PhenomenonReport.model_fields
        assert "family_id" not in PhenomenonReport.model_fields

    def test_perceive_takes_only_telemetry_and_material(self) -> None:
        import inspect

        assert set(inspect.signature(perceive).parameters) == {"telemetry", "material"}


class TestFeatures:
    def test_computes_the_full_set_when_signals_are_present(self) -> None:
        names = {f.name for f in _report(FaultCode.CLOG_PARTIAL).features}
        assert names == set(NOMINAL_BANDS)

    def test_missing_signal_yields_uncomputable_features_not_silence(self) -> None:
        """'I could not measure it' must be distinguishable from 'it looked normal'."""
        report = _report(FaultCode.CLOG_PARTIAL, dropped=("extruder_current",))
        assert report.feature("current_delta") is None
        assert report.uncomputable_features == ["current_delta", "current_mean"]
        assert report.missing_signals == ["extruder_current"]

    def test_flags_values_outside_the_nominal_band(self) -> None:
        flagged = {f.name for f in _report(FaultCode.CLOG_FULL).features if f.exceeded}
        assert "flow_tail_mean" in flagged

    def test_healthy_prints_stay_inside_the_flow_band(self) -> None:
        report = _report(FaultCode.NORMAL_SUSPICIOUS, seed=3)
        tail = report.feature("flow_tail_mean")
        assert tail is not None and not tail.exceeded

    def test_current_delta_sign_separates_the_confusable_pair(self) -> None:
        clog = _report(FaultCode.CLOG_PARTIAL, seed=5).feature("current_delta")
        param = _report(FaultCode.UNDEREXT_PARAM, seed=5).feature("current_delta")
        assert clog is not None and param is not None
        assert clog.value > 0.02
        assert abs(param.value) < 0.02

    def test_every_feature_carries_a_unit(self) -> None:
        assert all(f.unit for f in _report(FaultCode.THERMAL_DRIFT).features)


class TestBand:
    def test_one_sided_bands(self) -> None:
        assert Band(low=0.5).contains(0.9)
        assert not Band(low=0.5).contains(0.4)
        assert Band(high=0.5).contains(0.4)
        assert not Band(high=0.5).contains(0.9)

    def test_two_sided_band(self) -> None:
        band = Band(low=0.0, high=1.0)
        assert band.contains(0.5)
        assert not band.contains(1.5)

    def test_bands_record_their_provenance(self) -> None:
        """A threshold with no recorded origin is indistinguishable from a guess."""
        assert all(band.source for band in NOMINAL_BANDS.values())
