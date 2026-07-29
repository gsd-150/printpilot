"""Synthetic FDM telemetry environment.

Not a digital twin: there is no real asset, no synchronisation, and no calibration.
It is a seeded generator of plausible process traces with known injected faults,
which is what makes the diagnosis task measurable at all.
"""

from __future__ import annotations

from printpilot.simulator.dataset import (
    DEFAULT_MASTER_SEED,
    CaseInput,
    CaseLabel,
    generate,
    load_cases,
    load_labels,
    write_dataset,
)
from printpilot.simulator.fault_injection import InjectionProfile, inject
from printpilot.simulator.quality_evaluator import QualityReport, evaluate_quality
from printpilot.simulator.scenario import (
    CONFUSABLE_PAIR,
    DISCRIMINATING_SIGNAL,
    INJECTABLE_FAULTS,
    MATERIAL_SETPOINTS,
    SCENARIO_VERSION,
    FamilyPlan,
    Geometry,
    Material,
    NoiseProfile,
    ScenarioFamily,
    Split,
    build_split_plan,
    split_sizes,
)
from printpilot.simulator.virtual_sensors import SIGNAL_NAMES, Telemetry, sample

__all__ = [
    "CONFUSABLE_PAIR",
    "DEFAULT_MASTER_SEED",
    "DISCRIMINATING_SIGNAL",
    "INJECTABLE_FAULTS",
    "MATERIAL_SETPOINTS",
    "SCENARIO_VERSION",
    "SIGNAL_NAMES",
    "CaseInput",
    "CaseLabel",
    "FamilyPlan",
    "Geometry",
    "InjectionProfile",
    "Material",
    "NoiseProfile",
    "QualityReport",
    "ScenarioFamily",
    "Split",
    "Telemetry",
    "build_split_plan",
    "evaluate_quality",
    "generate",
    "inject",
    "load_cases",
    "load_labels",
    "sample",
    "split_sizes",
    "write_dataset",
]
