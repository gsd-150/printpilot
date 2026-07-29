"""Independent quality assessment.

This module exists to break a circularity the plan review flagged (P0-5). If the
simulator injects a fault at a threshold, perception detects it at that same
threshold, and "did the fix work?" is answered by asking whether the fault flag
cleared, then a high closed-loop score measures nothing but the consistency of one
set of constants with itself.

So closed-loop improvement is judged here instead, and this module:

* takes **only** :class:`Telemetry` — it never sees the fault code, the injection
  parameters, or the diagnosis;
* uses its own constants, deliberately not shared with ``fault_injection``;
* scores the *outcome* (how much material went missing, how far temperature
  strayed) rather than the *cause*.

That weakens the coupling; it does not remove it. Both sides still read traces
produced by the same generator, so results here bound what synthetic data can show
and should be reported as such.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from printpilot.simulator.virtual_sensors import Telemetry

#: Mean per-layer extrusion shortfall at which quality is considered wholly lost.
#: Chosen independently of the residual-flow bands used when injecting faults.
DEFICIT_AT_TOTAL_LOSS: Final = 0.30

#: Thermal excursion, in multiples of the material tolerance, at which the thermal
#: term saturates.
EXCURSION_AT_TOTAL_LOSS: Final = 4.0

WEIGHT_EXTRUSION: Final = 0.75
WEIGHT_THERMAL: Final = 0.25


class QualityReport(BaseModel):
    """Outcome-based quality, independent of any diagnosis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0, description="1.0 is nominal, 0.0 is total loss.")
    extrusion_deficit: float = Field(ge=0.0)
    thermal_excursion: float = Field(ge=0.0, description="In multiples of tolerance.")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def evaluate_quality(telemetry: Telemetry) -> QualityReport:
    """Score a print from its telemetry alone.

    The signature is the guarantee: there is no parameter through which a fault
    label could reach this function.
    """
    flow = telemetry.signals.get("flow_ratio", [])
    # Only shortfall counts. Noise pushing a layer above 1.0 is not a credit that
    # can offset a genuinely starved layer elsewhere.
    deficit = sum(max(0.0, 1.0 - v) for v in flow) / len(flow) if flow else 0.0

    temps = telemetry.signals.get("hotend_temp", [])
    setpoint = telemetry.setpoints.get("nozzle_temp")
    tolerance = telemetry.setpoints.get("temp_tolerance", 3.0)
    if temps and setpoint is not None and tolerance > 0:
        excursion = sum(abs(t - setpoint) for t in temps) / len(temps) / tolerance
    else:
        excursion = 0.0

    loss = WEIGHT_EXTRUSION * _clamp01(deficit / DEFICIT_AT_TOTAL_LOSS) + (
        WEIGHT_THERMAL * _clamp01(excursion / EXCURSION_AT_TOTAL_LOSS)
    )
    return QualityReport(
        case_id=telemetry.case_id,
        score=_clamp01(1.0 - loss),
        extrusion_deficit=deficit,
        thermal_excursion=excursion,
    )
