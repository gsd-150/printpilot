"""Material process windows — *recommended* ranges, not device limits.

Kept separate from ``params.HARDWARE_BOUNDS`` because the two answer different
questions and merging them breaks the gate in one direction or the other:

* **Hardware bounds** are what the machine physically tolerates. Crossing them can
  damage equipment, so they are refused outright.
* **Process windows** are what a material prints well at. Leaving one produces a
  worse part, not a broken printer, and there are legitimate reasons to do it —
  so this is advisory, and departing from it is a warning rather than a rejection.

Collapsing them would either block legitimate tuning or let a genuinely damaging
value through under the banner of "the material chart allows it".
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

from printpilot.domain.params import ParamName


class ProcessWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    material: str
    param: ParamName
    low: float
    high: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


def _window(material: str, param: ParamName, low: float, high: float) -> ProcessWindow:
    return ProcessWindow(material=material, param=param, low=low, high=high)


PROCESS_WINDOWS: Final[dict[tuple[str, ParamName], ProcessWindow]] = {
    (w.material, w.param): w
    for w in (
        _window("PLA", ParamName.NOZZLE_TEMP, 190.0, 220.0),
        _window("PLA", ParamName.BED_TEMP, 50.0, 70.0),
        _window("PETG", ParamName.NOZZLE_TEMP, 225.0, 250.0),
        _window("PETG", ParamName.BED_TEMP, 70.0, 90.0),
        _window("ABS", ParamName.NOZZLE_TEMP, 230.0, 260.0),
        _window("ABS", ParamName.BED_TEMP, 90.0, 110.0),
        _window("TPU", ParamName.NOZZLE_TEMP, 210.0, 235.0),
        _window("TPU", ParamName.BED_TEMP, 30.0, 60.0),
    )
}


def window_for(material: str, param: ParamName) -> ProcessWindow | None:
    """``None`` where no window is published — absence of guidance, not approval."""
    return PROCESS_WINDOWS.get((material, param))
