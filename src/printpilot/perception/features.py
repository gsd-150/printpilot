"""Deterministic feature extraction — the perception node.

No LLM is involved. Averaging a list is not a task worth spending a model call or
a hallucination budget on, and keeping it in code means the numbers a diagnosis
reasons over are reproducible.

Perception **measures**; it does not judge. Each feature carries the nominal band
it was compared against, so a downstream reader (rule baseline or model) can see
both the value and what counts as ordinary — but the mapping from "outside the
band" to "this fault" is deliberately not made here.
"""

from __future__ import annotations

from statistics import mean

from printpilot.domain import PhenomenonReport, SignalFeature
from printpilot.perception.calibration import (
    DEFICIT_LAYER_THRESHOLD,
    FEATURE_REQUIREMENTS,
    FEATURE_UNITS,
    NOMINAL_BANDS,
    WINDOW_FRACTION,
)
from printpilot.simulator import Telemetry


def _tail(values: list[float]) -> list[float]:
    return values[int(len(values) * (1.0 - WINDOW_FRACTION)) :]


def _head(values: list[float]) -> list[float]:
    return values[: max(1, int(len(values) * WINDOW_FRACTION))]


def _deficit_fraction(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if v < DEFICIT_LAYER_THRESHOLD) / len(values)


def _compute(telemetry: Telemetry) -> dict[str, float]:
    """Every feature the available signals allow, and no others."""
    out: dict[str, float] = {}

    flow = telemetry.signals.get("flow_ratio")
    if flow:
        out["flow_tail_mean"] = mean(_tail(flow))
        out["flow_min"] = min(flow)
        out["flow_deficit_fraction"] = _deficit_fraction(flow)
        out["flow_tail_deficit_fraction"] = _deficit_fraction(_tail(flow))

    current = telemetry.signals.get("extruder_current")
    if current:
        out["current_mean"] = mean(current)
        # Late minus early. The *sign* is what matters: a restriction raises the
        # force needed over time, a low flow setting does not.
        out["current_delta"] = mean(_tail(current)) - mean(_head(current))

    temps = telemetry.signals.get("hotend_temp")
    setpoint = telemetry.setpoints.get("nozzle_temp")
    if temps and setpoint:
        # Normalised by setpoint so the band means the same thing for PLA at 205 °C
        # and ABS at 245 °C. Both magnitude *and* sign are emitted: the magnitude
        # says a correction is needed, the sign says which way. Publishing only the
        # magnitude left the decision layer able to push one direction and no other.
        tail_temps = _tail(temps)
        out["temp_deviation_tail"] = mean(abs(t - setpoint) for t in tail_temps) / setpoint
        out["temp_bias_tail"] = mean(t - setpoint for t in tail_temps) / setpoint

    return out


def perceive(telemetry: Telemetry, material: str) -> PhenomenonReport:
    """Turn raw traces into a structured report.

    ``material`` is passed in rather than read from case metadata: the operator
    knows which filament is loaded, but nothing else about the case may cross into
    the report.
    """
    values = _compute(telemetry)

    features = [
        SignalFeature(
            name=name,
            value=value,
            unit=FEATURE_UNITS[name],
            threshold=_reference_bound(name, value),
            exceeded=not NOMINAL_BANDS[name].contains(value),
        )
        for name, value in values.items()
    ]

    uncomputable = sorted(
        name for name, signal in FEATURE_REQUIREMENTS.items() if signal not in telemetry.signals
    )

    return PhenomenonReport(
        case_id=telemetry.case_id,
        material=material,
        features=features,
        available_signals=telemetry.available_signals,
        missing_signals=telemetry.missing_signals,
        uncomputable_features=uncomputable,
    )


def _reference_bound(name: str, value: float) -> float | None:
    """The band edge the value is judged against, for display alongside it."""
    band = NOMINAL_BANDS[name]
    if band.high is not None and value > band.high:
        return band.high
    if band.low is not None and value < band.low:
        return band.low
    return band.high if band.high is not None else band.low
