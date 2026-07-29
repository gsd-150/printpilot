"""Nominal reference bands, calibrated from the dev split.

These numbers were **measured, not copied**. Reusing the simulator's injection
constants as detection thresholds is the circularity the plan review flagged
(P0-5): the pipeline would then be checking the generator against itself.

Each band is the observed envelope of ``NORMAL_SUSPICIOUS`` cases in dev — that is,
what a healthy print looks like, including its transient dips. Nothing here is
derived from a fault class, so the bands describe *normality* rather than encoding
the answer to any particular fault.

``printpilot calibrate`` recomputes the underlying percentiles, and
``tests/test_calibration.py`` asserts these constants still match the data, so a
change to the generator that invalidates them fails the build instead of silently
degrading perception.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

#: Fraction of the trace treated as "head" and "tail" when comparing early to late.
WINDOW_FRACTION: Final = 0.25

#: A layer is counted as short when flow falls below this. Set just under the
#: nominal median so ordinary noise does not register as a deficit.
DEFICIT_LAYER_THRESHOLD: Final = 0.97


class Band(BaseModel):
    """A nominal range. Values outside it are notable, not necessarily faulty."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    low: float | None = None
    high: float | None = None
    source: str = ""

    def contains(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return False
        return not (self.high is not None and value > self.high)


#: Calibrated on dev at master_seed=42. `source` records the percentile each bound
#: came from, so the provenance survives copy-paste.
NOMINAL_BANDS: Final[dict[str, Band]] = {
    "flow_tail_mean": Band(low=0.985, source="NORMAL_SUSPICIOUS dev p05=0.9902"),
    "flow_min": Band(low=0.70, source="NORMAL_SUSPICIOUS dev p05=0.7313"),
    "flow_deficit_fraction": Band(high=0.35, source="NORMAL_SUSPICIOUS dev p95=0.3115"),
    "flow_tail_deficit_fraction": Band(high=0.32, source="NORMAL_SUSPICIOUS dev p95=0.2894"),
    "current_mean": Band(low=0.345, high=0.356, source="NORMAL_SUSPICIOUS dev p05..p95"),
    "current_delta": Band(low=-0.012, high=0.008, source="NORMAL_SUSPICIOUS dev p05..p95"),
    "temp_deviation_tail": Band(high=0.045, source="NORMAL_SUSPICIOUS dev p95=0.0408"),
}

FEATURE_UNITS: Final[dict[str, str]] = {
    "flow_tail_mean": "ratio",
    "flow_min": "ratio",
    "flow_deficit_fraction": "fraction_of_layers",
    "flow_tail_deficit_fraction": "fraction_of_layers",
    "current_mean": "ampere",
    "current_delta": "ampere",
    "temp_deviation_tail": "fraction_of_setpoint",
}

#: Which telemetry signal each feature needs. Used to report what could not be
#: computed rather than silently emitting a shorter feature list.
FEATURE_REQUIREMENTS: Final[dict[str, str]] = {
    "flow_tail_mean": "flow_ratio",
    "flow_min": "flow_ratio",
    "flow_deficit_fraction": "flow_ratio",
    "flow_tail_deficit_fraction": "flow_ratio",
    "current_mean": "extruder_current",
    "current_delta": "extruder_current",
    "temp_deviation_tail": "hotend_temp",
}
