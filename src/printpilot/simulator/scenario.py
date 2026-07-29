"""Scenario families and the dataset split plan.

Splitting is by **family**, never by row. A family is a combination of
``(fault, material, geometry, noise, dropped signals)``; every case drawn from one
family shares its generating structure, so putting two cases from the same family
on opposite sides of a split would leak that structure across the boundary and
inflate the measured score.

The three splits differ deliberately:

* ``dev`` — what development and prompt iteration may see.
* ``holdout`` — same axes as dev, different material/geometry combinations. This
  is the gate for accepting or rejecting a change.
* ``challenge`` — each sub-group varies **one novel factor** against an otherwise
  familiar setting: an unseen material, out-of-range noise, or the loss of the
  very signal that separates a clog from a parameter problem. Isolating one factor
  at a time is why the geometries here overlap with dev; the point is to attribute
  a drop to a specific cause, not to change everything at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from printpilot.domain import FaultCode

SCENARIO_VERSION: Final = "1.0.0"


class Material(StrEnum):
    PLA = "PLA"
    PETG = "PETG"
    ABS = "ABS"

    # Reserved for the challenge split: never seen during development.
    TPU = "TPU"


class Geometry(StrEnum):
    BOX = "box"
    CYLINDER = "cylinder"
    BRACKET = "bracket"
    THIN_WALL = "thin_wall"
    LATTICE = "lattice"


class NoiseProfile(StrEnum):
    LOW = "low"
    NOMINAL = "nominal"
    HIGH = "high"

    # Beyond anything present in dev — a stress case, not a realistic default.
    BOUNDARY = "boundary"


class Split(StrEnum):
    DEV = "dev"
    HOLDOUT = "holdout"
    CHALLENGE = "challenge"


#: Nozzle and bed setpoints per material, and the tolerance the quality evaluator
#: treats as acceptable thermal deviation.
MATERIAL_SETPOINTS: Final[dict[Material, dict[str, float]]] = {
    Material.PLA: {"nozzle_temp": 205.0, "bed_temp": 60.0, "temp_tolerance": 3.0},
    Material.PETG: {"nozzle_temp": 235.0, "bed_temp": 80.0, "temp_tolerance": 3.5},
    Material.ABS: {"nozzle_temp": 245.0, "bed_temp": 100.0, "temp_tolerance": 4.0},
    Material.TPU: {"nozzle_temp": 225.0, "bed_temp": 45.0, "temp_tolerance": 4.0},
}

#: Per-layer sensor noise sigma (as a fraction of the nominal signal value).
NOISE_SIGMA: Final[dict[NoiseProfile, float]] = {
    NoiseProfile.LOW: 0.008,
    NoiseProfile.NOMINAL: 0.020,
    NoiseProfile.HIGH: 0.045,
    NoiseProfile.BOUNDARY: 0.080,
}

#: The signal that separates a mechanical clog from a parameter-set under-extrusion.
DISCRIMINATING_SIGNAL: Final = "extruder_current"


@dataclass(frozen=True, order=True)
class ScenarioFamily:
    """The unit of dataset splitting."""

    fault: FaultCode
    material: Material
    geometry: Geometry
    noise: NoiseProfile
    dropped_signals: tuple[str, ...] = ()

    @property
    def family_id(self) -> str:
        parts = [self.fault.value, self.material.value, self.geometry.value, self.noise.value]
        if self.dropped_signals:
            parts.append(f"-{'-'.join(self.dropped_signals)}")
        return "/".join(parts)


@dataclass(frozen=True)
class FamilyPlan:
    family: ScenarioFamily
    cases: int


#: Faults that can occur in any scenario. NORMAL_SUSPICIOUS is included on purpose:
#: a dataset without negatives cannot measure whether the system knows to do nothing.
INJECTABLE_FAULTS: Final[tuple[FaultCode, ...]] = (
    FaultCode.CLOG_PARTIAL,
    FaultCode.CLOG_FULL,
    FaultCode.UNDEREXT_PARAM,
    FaultCode.THERMAL_DRIFT,
    FaultCode.NORMAL_SUSPICIOUS,
)

#: The pair the whole benchmark turns on: similar flow curves, opposite responses.
CONFUSABLE_PAIR: Final[tuple[FaultCode, FaultCode]] = (
    FaultCode.CLOG_PARTIAL,
    FaultCode.UNDEREXT_PARAM,
)

_DEV_SETTINGS: Final[tuple[tuple[Material, Geometry, NoiseProfile], ...]] = (
    (Material.PLA, Geometry.BOX, NoiseProfile.NOMINAL),
    (Material.PLA, Geometry.CYLINDER, NoiseProfile.LOW),
    (Material.PETG, Geometry.BRACKET, NoiseProfile.NOMINAL),
    (Material.ABS, Geometry.BOX, NoiseProfile.HIGH),
)

_HOLDOUT_SETTINGS: Final[tuple[tuple[Material, Geometry, NoiseProfile], ...]] = (
    (Material.PETG, Geometry.THIN_WALL, NoiseProfile.NOMINAL),
    (Material.ABS, Geometry.LATTICE, NoiseProfile.LOW),
)


def _plans(
    settings: tuple[tuple[Material, Geometry, NoiseProfile], ...],
    cases_per_family: int,
    *,
    dropped: tuple[str, ...] = (),
    faults: tuple[FaultCode, ...] = INJECTABLE_FAULTS,
) -> tuple[FamilyPlan, ...]:
    return tuple(
        FamilyPlan(
            family=ScenarioFamily(
                fault=fault,
                material=material,
                geometry=geometry,
                noise=noise,
                dropped_signals=dropped,
            ),
            cases=cases_per_family,
        )
        for fault in faults
        for material, geometry, noise in settings
    )


def build_split_plan() -> dict[Split, tuple[FamilyPlan, ...]]:
    """The dataset composition: dev 100 / holdout 30 / challenge 30 = 160.

    Fixed rather than sampled, so the composition is reviewable and stable across
    regenerations.
    """
    challenge: tuple[FamilyPlan, ...] = (
        # (a) unseen material — TPU appears nowhere in dev or holdout.
        *_plans(((Material.TPU, Geometry.THIN_WALL, NoiseProfile.NOMINAL),), 2),
        # (b) out-of-range sensor noise, otherwise the most familiar setting there is.
        *_plans(((Material.PLA, Geometry.BOX, NoiseProfile.BOUNDARY),), 2),
        # (c) the discriminating signal is gone. Restricted to the confusable pair,
        #     where losing it should force an abstention rather than a coin flip.
        *_plans(
            ((Material.PETG, Geometry.BRACKET, NoiseProfile.NOMINAL),),
            5,
            dropped=(DISCRIMINATING_SIGNAL,),
            faults=CONFUSABLE_PAIR,
        ),
    )
    return {
        Split.DEV: _plans(_DEV_SETTINGS, 5),
        Split.HOLDOUT: _plans(_HOLDOUT_SETTINGS, 3),
        Split.CHALLENGE: challenge,
    }


def split_sizes() -> dict[Split, int]:
    return {split: sum(p.cases for p in plans) for split, plans in build_split_plan().items()}
