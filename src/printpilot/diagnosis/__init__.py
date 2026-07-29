"""Diagnosis strategies.

``rules`` is the deterministic control arm of the ablation and the degraded path;
the LLM-backed diagnoser joins it here.
"""

from __future__ import annotations

from printpilot.diagnosis.rules import DIAGNOSER_NAME, diagnose

__all__ = ["DIAGNOSER_NAME", "diagnose"]
