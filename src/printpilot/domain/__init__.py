"""Domain vocabulary: parameters, faults, and the contracts nodes exchange."""

from __future__ import annotations

from printpilot.domain.faults import (
    FAULT_CATALOG,
    FaultCode,
    FaultSpec,
    RemediationClass,
    remediation_for,
)
from printpilot.domain.params import (
    HARDWARE_BOUNDS,
    PARAM_UNITS,
    HardwareBound,
    ParamName,
    ParamUnit,
)
from printpilot.domain.schemas import (
    ActionPlan,
    ActionType,
    DiagnosisResult,
    EvidenceKind,
    EvidenceRef,
    Hypothesis,
    KnowledgePriority,
    ParamDelta,
    PhenomenonReport,
    RiskLevel,
    SafetyDecision,
    SafetyVerdict,
    SignalFeature,
)

__all__ = [
    "FAULT_CATALOG",
    "HARDWARE_BOUNDS",
    "PARAM_UNITS",
    "ActionPlan",
    "ActionType",
    "DiagnosisResult",
    "EvidenceKind",
    "EvidenceRef",
    "FaultCode",
    "FaultSpec",
    "HardwareBound",
    "Hypothesis",
    "KnowledgePriority",
    "ParamDelta",
    "ParamName",
    "ParamUnit",
    "PhenomenonReport",
    "RemediationClass",
    "RiskLevel",
    "SafetyDecision",
    "SafetyVerdict",
    "SignalFeature",
    "remediation_for",
]
