"""Harness layer: what turns the pipeline from a demo into something operable.

Currently bounded concurrency and run accounting. Trace and degradation land with
the SafetyGate in M7.
"""

from __future__ import annotations

from printpilot.harness.concurrency import (
    DEFAULT_WORKERS,
    MAX_WORKERS,
    map_bounded,
    resolve_workers,
)
from printpilot.harness.cost import RunCost, collect_cost, format_cost
from printpilot.harness.trace import DISABLED, TRACES_ROOT, Step, TraceEvent, Tracer

__all__ = [
    "DEFAULT_WORKERS",
    "DISABLED",
    "MAX_WORKERS",
    "TRACES_ROOT",
    "RunCost",
    "Step",
    "TraceEvent",
    "Tracer",
    "collect_cost",
    "format_cost",
    "map_bounded",
    "resolve_workers",
]
