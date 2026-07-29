"""The closed loop: act, re-print, and have an independent judge score the result."""

from __future__ import annotations

from printpilot.loop.closed_loop import (
    DEMO_FAULTS,
    SIGNIFICANT_QUALITY_CHANGE,
    LoopOutcome,
    LoopResult,
    demo_families,
    run_round,
)

__all__ = [
    "DEMO_FAULTS",
    "SIGNIFICANT_QUALITY_CHANGE",
    "LoopOutcome",
    "LoopResult",
    "demo_families",
    "run_round",
]
