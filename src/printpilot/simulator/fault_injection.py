"""Noise-free per-layer traces for each fault.

The model is a coarse physical approximation, not a validated process simulation —
it is calibrated to nothing. What it does guarantee is the property the benchmark
is built around:

    ``CLOG_PARTIAL`` and ``UNDEREXT_PARAM`` overlap on the flow-ratio curve and are
    separated mainly by extruder current.

A mechanical restriction raises the force needed to push filament, so current
climbs as flow falls. A flow-percentage set too low simply extrudes less at normal
resistance, so current stays flat. That single asymmetry is what a diagnosis has to
find, and it is why the challenge split includes cases with the current signal
removed: without it, the honest answer is ``UNKNOWN``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Final

from printpilot.domain import FaultCode
from printpilot.simulator.scenario import MATERIAL_SETPOINTS, Material

#: Nominal extruder current under normal resistance, in amperes (virtual sensor).
BASE_CURRENT: Final = 0.35

#: Range for how strongly a mechanical restriction couples flow loss into current
#: draw. Drawn per case rather than fixed: with a single constant, current would be
#: an exact function of flow and a rule could invert it, which is not a diagnosis.
CLOG_CURRENT_GAIN: Final = (0.40, 0.70)

#: Residual flow bands for the confusable pair. These **overlap on purpose**.
#: An earlier version used disjoint bands (0.62–0.84 against 0.86–0.95), which let a
#: single threshold on flow ratio separate them perfectly — the benchmark would have
#: measured nothing but that threshold. Within the shared region the flow curve is
#: genuinely uninformative and the current signal has to carry the decision.
CLOG_PARTIAL_RESIDUAL: Final = (0.72, 0.93)
UNDEREXT_PARAM_RESIDUAL: Final = (0.80, 0.95)

#: Nominal heater duty cycle when holding setpoint.
BASE_DUTY: Final = 0.42


@dataclass(frozen=True)
class PrintParams:
    """The settings a print runs with — the loop's only lever.

    ``nozzle_temp_offset`` shifts the *commanded* setpoint. The material target in
    ``MATERIAL_SETPOINTS`` stays fixed and remains what quality is judged against,
    so raising the setpoint to counteract a downward drift genuinely moves the
    measured temperature back toward target rather than moving the goalposts.

    Defaults reproduce the un-patched behaviour exactly, so the published dataset
    digests are unaffected by this parameter existing.
    """

    flow_percent: float = 100.0
    nozzle_temp_offset: float = 0.0

    @property
    def flow_scale(self) -> float:
        return self.flow_percent / 100.0


NOMINAL_PARAMS = PrintParams()


@dataclass(frozen=True)
class InjectionProfile:
    """Clean traces before sensor noise is applied."""

    flow_ratio: list[float]
    extruder_current: list[float]
    hotend_temp: list[float]
    hotend_duty: list[float]
    onset_layer: int | None
    #: Residual flow the fault settles at; ``None`` where the concept does not apply.
    residual_flow: float | None


def _flat(value: float, n: int) -> list[float]:
    return [value] * n


def _ramp(start: float, end: float, steps: int) -> list[float]:
    if steps <= 1:
        return [end]
    return [start + (end - start) * i / (steps - 1) for i in range(steps)]


def inject(
    fault: FaultCode,
    *,
    layer_count: int,
    material: Material,
    rng: random.Random,
    params: PrintParams = NOMINAL_PARAMS,
) -> InjectionProfile:
    """Build the clean traces for one case under the given settings.

    How each fault responds to a parameter change is the physics the closed loop
    depends on, and getting it wrong would make the loop measure nothing:

    * ``UNDEREXT_PARAM`` — flow percentage scales commanded extrusion directly, so
      raising it genuinely fixes the shortfall.
    * ``CLOG_*`` — the restriction, not the setting, limits output. Raising flow
      does **not** increase what comes out; it increases the force pushing against
      the blockage. So flow stays where it was and current climbs. A loop that
      patches a clog therefore measures *harm*, not merely a lack of improvement.
    * ``THERMAL_DRIFT`` — a setpoint offset moves the measured temperature relative
      to the fixed material target.
    """
    setpoint = MATERIAL_SETPOINTS[material]["nozzle_temp"]
    temp = _flat(setpoint + params.nozzle_temp_offset, layer_count)
    duty = _flat(BASE_DUTY, layer_count)
    onset: int | None = None
    residual: float | None = None

    match fault:
        case FaultCode.CLOG_PARTIAL:
            # Gradual restriction: flow decays over a ramp, current rises with it.
            onset = rng.randint(int(layer_count * 0.2), int(layer_count * 0.55))
            residual = rng.uniform(*CLOG_PARTIAL_RESIDUAL)
            ramp_len = rng.randint(6, 14)
            flow = _flat(1.0, onset)
            flow += _ramp(1.0, residual, min(ramp_len, layer_count - onset))
            flow += _flat(residual, layer_count - len(flow))
            # Resistance rises as the passage narrows: current climbs while flow
            # falls. Commanding more flow does not widen the passage — it only
            # pushes harder against it, so the scale applies to current alone.
            gain = rng.uniform(*CLOG_CURRENT_GAIN)
            current = [(BASE_CURRENT + gain * (1.0 - f)) * params.flow_scale for f in flow]

        case FaultCode.CLOG_FULL:
            # Flow collapses within a couple of layers. Current spikes as the drive
            # gear loads up, then falls away once it is grinding rather than pushing.
            onset = rng.randint(int(layer_count * 0.25), int(layer_count * 0.6))
            residual = rng.uniform(0.02, 0.09)
            flow = _flat(1.0, onset)
            flow += _ramp(1.0, residual, min(3, layer_count - onset))
            flow += _flat(residual, layer_count - len(flow))
            current = []
            for i in range(layer_count):
                if onset <= i < onset + 3:
                    current.append(BASE_CURRENT * rng.uniform(2.4, 3.1) * params.flow_scale)
                elif i >= onset + 3:
                    current.append(BASE_CURRENT * rng.uniform(0.35, 0.55) * params.flow_scale)
                else:
                    current.append(BASE_CURRENT * params.flow_scale)

        case FaultCode.UNDEREXT_PARAM:
            # A setting, not an event: present from layer zero, resistance normal.
            # Flow percentage scales commanded extrusion, so raising it is the fix.
            residual = min(1.0, rng.uniform(*UNDEREXT_PARAM_RESIDUAL) * params.flow_scale)
            flow = _flat(residual, layer_count)
            # Pushing less material takes slightly *less* force, so current sits a
            # touch below nominal. The magnitudes are close to a mild clog's; what
            # differs is the sign of the coupling — up with a restriction, gently
            # down with a low flow setting. That sign is the discriminator.
            current = _flat(BASE_CURRENT * (0.90 + 0.10 * residual), layer_count)

        case FaultCode.THERMAL_DRIFT:
            onset = rng.randint(int(layer_count * 0.15), int(layer_count * 0.5))
            drift = rng.choice([-1.0, 1.0]) * rng.uniform(8.0, 18.0)
            # Measured temperature tracks the *commanded* setpoint, which the offset
            # moves; quality is judged against the fixed material target, so raising
            # the setpoint against a downward drift is a genuine correction rather
            # than a relocation of the goalposts.
            commanded = setpoint + params.nozzle_temp_offset
            temp = [
                commanded if i < onset else commanded + drift * min(1.0, (i - onset) / 8.0)
                for i in range(layer_count)
            ]
            # The heater works against the drift, so duty moves opposite to it.
            duty = [
                BASE_DUTY if i < onset else BASE_DUTY - 0.012 * (temp[i] - commanded)
                for i in range(layer_count)
            ]
            # Off-window temperature perturbs flow mildly, nowhere near clog levels.
            residual = min(1.0, rng.uniform(0.94, 0.985) * params.flow_scale)
            flow = [1.0 if i < onset else residual for i in range(layer_count)]
            current = _flat(BASE_CURRENT * params.flow_scale, layer_count)

        case FaultCode.NORMAL_SUSPICIOUS:
            # Transient dips from a filament change or geometry switch. They recover,
            # and resistance never rises — the correct response is to do nothing.
            flow = _flat(1.0, layer_count)
            # Dips start early enough that the recovery is inside the trace. A dip
            # in the final layers is genuinely indistinguishable from the onset of a
            # clog, so labelling one "normal" would be scoring an unanswerable case.
            last_start = max(1, int(layer_count * 0.85) - 4)
            for _ in range(rng.randint(1, 2)):
                start = rng.randint(1, last_start)
                depth = rng.uniform(0.10, 0.24)
                for i in range(start, min(start + rng.randint(1, 3), layer_count)):
                    flow[i] = 1.0 - depth
            current = _flat(BASE_CURRENT, layer_count)

        case _:
            msg = f"{fault} is not injectable"
            raise ValueError(msg)

    return InjectionProfile(
        flow_ratio=flow[:layer_count],
        extruder_current=current[:layer_count],
        hotend_temp=temp[:layer_count],
        hotend_duty=duty[:layer_count],
        onset_layer=onset,
        residual_flow=residual,
    )
