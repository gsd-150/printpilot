"""Virtual sensors.

Every signal here is **synthetic**. Some have no direct equivalent on a stock
consumer FDM printer: ``flow_ratio`` presumes a filament encoder measuring actual
against commanded extrusion, and ``extruder_current`` presumes drive-motor current
sensing. The plan's claim that real data could later be swapped in "by replacing
the input layer" is therefore optimistic, and is recorded as a known limitation
rather than glossed over.

Sensor dropout is modelled explicitly instead of by writing ``NaN``: a missing
signal is absent from :attr:`Telemetry.signals` entirely, so downstream code has
to decide what to do about it rather than silently propagating a placeholder.
"""

from __future__ import annotations

import random

from pydantic import BaseModel, ConfigDict, Field

from printpilot.simulator.fault_injection import InjectionProfile
from printpilot.simulator.scenario import NOISE_SIGMA, NoiseProfile

SIGNAL_NAMES: tuple[str, ...] = (
    "flow_ratio",
    "extruder_current",
    "hotend_temp",
    "hotend_duty",
)


class Telemetry(BaseModel):
    """Per-layer synthetic traces for one print."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    layer_count: int = Field(gt=0)
    signals: dict[str, list[float]]
    setpoints: dict[str, float]

    @property
    def available_signals(self) -> list[str]:
        return sorted(self.signals)

    @property
    def missing_signals(self) -> list[str]:
        return sorted(set(SIGNAL_NAMES) - set(self.signals))


def _noisy(values: list[float], sigma: float, rng: random.Random) -> list[float]:
    """Multiplicative noise, so sigma means the same thing across signals whose
    magnitudes differ by two orders (a 0.35 A current and a 245 °C temperature)."""
    return [v * (1.0 + rng.gauss(0.0, sigma)) for v in values]


def sample(
    profile: InjectionProfile,
    *,
    case_id: str,
    noise: NoiseProfile,
    rng: random.Random,
    setpoints: dict[str, float],
    dropped_signals: tuple[str, ...] = (),
) -> Telemetry:
    """Apply sensor noise and dropout to clean traces."""
    sigma = NOISE_SIGMA[noise]
    clean = {
        "flow_ratio": profile.flow_ratio,
        "extruder_current": profile.extruder_current,
        "hotend_temp": profile.hotend_temp,
        "hotend_duty": profile.hotend_duty,
    }

    unknown = set(dropped_signals) - set(SIGNAL_NAMES)
    if unknown:
        msg = f"cannot drop unknown signal(s): {sorted(unknown)}"
        raise ValueError(msg)

    signals = {
        name: _noisy(values, sigma, rng)
        for name, values in clean.items()
        if name not in dropped_signals
    }
    return Telemetry(
        case_id=case_id,
        layer_count=len(profile.flow_ratio),
        signals=signals,
        setpoints=setpoints,
    )
