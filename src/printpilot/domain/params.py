"""Printer parameters, their units, and *hardware* safety bounds.

Note the deliberate separation required by the plan (SG-3):

* **Hardware bounds** (this module) are physical limits of the device. Crossing
  them can damage equipment, so they are non-negotiable and enforced in code.
* **Process windows** (``process_windows.py``, landing with the SafetyGate in M7)
  are *material-recommended* ranges. They are advisory and may legitimately be
  exceeded with justification.

Collapsing the two is a common modelling mistake: it either makes the safety
gate too permissive or blocks legitimate parameter tuning.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class ParamName(StrEnum):
    """Tunable print parameters.

    A closed enum rather than free text: the SafetyGate must never have to
    interpret a parameter name it has no bound for.
    """

    NOZZLE_TEMP = "nozzle_temp"
    BED_TEMP = "bed_temp"
    FLOW = "flow"
    PRINT_SPEED = "print_speed"
    RETRACT_DISTANCE = "retract_distance"
    FAN_SPEED = "fan_speed"


class ParamUnit(StrEnum):
    CELSIUS = "celsius"
    MM = "mm"
    MM_S = "mm_s"
    PERCENT = "percent"


PARAM_UNITS: Final[dict[ParamName, ParamUnit]] = {
    ParamName.NOZZLE_TEMP: ParamUnit.CELSIUS,
    ParamName.BED_TEMP: ParamUnit.CELSIUS,
    ParamName.FLOW: ParamUnit.PERCENT,
    ParamName.PRINT_SPEED: ParamUnit.MM_S,
    ParamName.RETRACT_DISTANCE: ParamUnit.MM,
    ParamName.FAN_SPEED: ParamUnit.PERCENT,
}


class HardwareBound(BaseModel):
    """Absolute device limits for one parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    param: ParamName
    unit: ParamUnit
    min_value: float
    max_value: float
    max_abs_delta: float = Field(
        description="Largest single-step change allowed, to rule out large jumps.",
        gt=0,
    )


HARDWARE_BOUNDS: Final[dict[ParamName, HardwareBound]] = {
    ParamName.NOZZLE_TEMP: HardwareBound(
        param=ParamName.NOZZLE_TEMP,
        unit=ParamUnit.CELSIUS,
        min_value=170.0,
        max_value=260.0,
        max_abs_delta=15.0,
    ),
    ParamName.BED_TEMP: HardwareBound(
        param=ParamName.BED_TEMP,
        unit=ParamUnit.CELSIUS,
        min_value=0.0,
        max_value=110.0,
        max_abs_delta=15.0,
    ),
    ParamName.FLOW: HardwareBound(
        param=ParamName.FLOW,
        unit=ParamUnit.PERCENT,
        min_value=80.0,
        max_value=120.0,
        max_abs_delta=10.0,
    ),
    ParamName.PRINT_SPEED: HardwareBound(
        param=ParamName.PRINT_SPEED,
        unit=ParamUnit.MM_S,
        min_value=10.0,
        max_value=200.0,
        max_abs_delta=30.0,
    ),
    ParamName.RETRACT_DISTANCE: HardwareBound(
        param=ParamName.RETRACT_DISTANCE,
        unit=ParamUnit.MM,
        min_value=0.0,
        max_value=8.0,
        max_abs_delta=2.0,
    ),
    ParamName.FAN_SPEED: HardwareBound(
        param=ParamName.FAN_SPEED,
        unit=ParamUnit.PERCENT,
        min_value=0.0,
        max_value=100.0,
        max_abs_delta=50.0,
    ),
}
