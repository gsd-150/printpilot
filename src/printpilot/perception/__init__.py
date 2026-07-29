"""Deterministic perception: telemetry in, structured phenomena out."""

from __future__ import annotations

from printpilot.perception.calibration import (
    DEFICIT_LAYER_THRESHOLD,
    FEATURE_REQUIREMENTS,
    FEATURE_UNITS,
    NOMINAL_BANDS,
    WINDOW_FRACTION,
    Band,
)
from printpilot.perception.features import perceive

__all__ = [
    "DEFICIT_LAYER_THRESHOLD",
    "FEATURE_REQUIREMENTS",
    "FEATURE_UNITS",
    "NOMINAL_BANDS",
    "WINDOW_FRACTION",
    "Band",
    "perceive",
]
