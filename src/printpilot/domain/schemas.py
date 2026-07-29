"""Payload contracts passed between pipeline nodes.

Two design rules, both load-bearing:

1. Nodes exchange **validated structures, not prose**. Natural-language handoff
   accumulates loss and cannot be unit-tested.
2. Every model sets ``extra="forbid"``. When an LLM invents a field, we want a
   validation error at the boundary rather than a silently ignored key.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from printpilot.domain.faults import FaultCode
from printpilot.domain.params import PARAM_UNITS, ParamName, ParamUnit

# --------------------------------------------------------------------- evidence


class EvidenceKind(StrEnum):
    SIGNAL = "signal"
    SKILL = "skill"
    RAG = "rag"
    HARD_RULE = "hard_rule"
    LLM_PRIOR = "llm_prior"


class KnowledgePriority(IntEnum):
    """Precedence when sources disagree (项目规划_v2 §5.5).

    hardware safety rule > reviewed Skill > sourced RAG evidence > LLM's own prior.
    Overridden lower-priority sources are recorded in the trace rather than dropped.
    """

    LLM_PRIOR = 0
    RAG = 1
    SKILL = 2
    HARD_RULE = 3


_PRIORITY_BY_KIND: dict[EvidenceKind, KnowledgePriority] = {
    EvidenceKind.LLM_PRIOR: KnowledgePriority.LLM_PRIOR,
    EvidenceKind.SIGNAL: KnowledgePriority.RAG,
    EvidenceKind.RAG: KnowledgePriority.RAG,
    EvidenceKind.SKILL: KnowledgePriority.SKILL,
    EvidenceKind.HARD_RULE: KnowledgePriority.HARD_RULE,
}


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    ref: str = Field(min_length=1, description="Signal name, skill name, or chunk id.")
    detail: str = ""

    @property
    def priority(self) -> KnowledgePriority:
        return _PRIORITY_BY_KIND[self.kind]


# ------------------------------------------------------------------- perception


class SignalFeature(BaseModel):
    """One extracted feature. Produced by deterministic code, never by an LLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: float
    unit: str
    threshold: float | None = None
    exceeded: bool = False


class PhenomenonReport(BaseModel):
    """Structured output of the deterministic PerceptionNode."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    scenario_family: str = Field(min_length=1)
    material: str = Field(min_length=1)
    features: list[SignalFeature] = Field(default_factory=list)
    available_signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(
        default_factory=list,
        description=(
            "Signals this case lacks. Skill routing degrades confidence on these "
            "rather than filtering the skill out entirely."
        ),
    )

    def feature(self, name: str) -> SignalFeature | None:
        return next((f for f in self.features if f.name == name), None)


# -------------------------------------------------------------------- diagnosis


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fault_code: FaultCode
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_evidence_unless_abstaining(self) -> Self:
        """A concrete root cause must cite something. Abstention need not."""
        if self.fault_code is not FaultCode.UNKNOWN and not self.evidence:
            msg = f"hypothesis {self.fault_code} must cite at least one piece of evidence"
            raise ValueError(msg)
        return self


class DiagnosisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    hypotheses: list[Hypothesis] = Field(min_length=1)
    skills_used: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sort_by_confidence(self) -> Self:
        self.hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return self

    @property
    def top(self) -> Hypothesis:
        return self.hypotheses[0]

    @property
    def abstained(self) -> bool:
        return self.top.fault_code is FaultCode.UNKNOWN


# --------------------------------------------------------------------- decision


class ActionType(StrEnum):
    """What the system proposes to do.

    v1 of the plan modelled the decision as a bare parameter patch. That is unsafe:
    it gives every fault the same exit, including ones where continuing to print is
    the wrong move. Clogs route to maintenance, not to compensation.
    """

    APPLY_PARAM_PATCH = "apply_param_patch"
    PAUSE_AND_INSPECT = "pause_and_inspect"
    MAINTENANCE_REQUIRED = "maintenance_required"
    ABORT_PRINT = "abort_print"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ParamDelta(BaseModel):
    """A single parameter change. The unit is mandatory and is cross-checked
    against the parameter — ``"+10"`` with no unit was a real defect in v1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    param: ParamName
    delta: float
    unit: ParamUnit

    @model_validator(mode="after")
    def _unit_must_match_param(self) -> Self:
        expected = PARAM_UNITS[self.param]
        if self.unit is not expected:
            msg = f"{self.param} is measured in {expected}, got {self.unit}"
            raise ValueError(msg)
        return self


class ActionPlan(BaseModel):
    """Proposed by the DecisionAgent. **Proposing is not permission** — the plan
    only takes effect once the deterministic SafetyGate allows it."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    action_type: ActionType
    patch: list[ParamDelta] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = True
    rollback_plan: str = Field(min_length=1)

    @field_validator("patch")
    @classmethod
    def _no_duplicate_params(cls, patch: list[ParamDelta]) -> list[ParamDelta]:
        names = [d.param for d in patch]
        if len(names) != len(set(names)):
            msg = "patch contains duplicate parameters"
            raise ValueError(msg)
        return patch

    @model_validator(mode="after")
    def _patch_only_with_patch_action(self) -> Self:
        has_patch = bool(self.patch)
        wants_patch = self.action_type is ActionType.APPLY_PARAM_PATCH
        if wants_patch and not has_patch:
            msg = "APPLY_PARAM_PATCH requires a non-empty patch"
            raise ValueError(msg)
        if not wants_patch and has_patch:
            msg = f"{self.action_type} must not carry a parameter patch"
            raise ValueError(msg)
        return self


# ----------------------------------------------------------------- safety gate


class SafetyDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"


class SafetyVerdict(BaseModel):
    """Deterministic ruling on an ActionPlan. Produced only by Python."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    decision: SafetyDecision
    violated_rules: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _blocked_needs_a_reason(self) -> Self:
        if self.decision is SafetyDecision.BLOCK and not self.violated_rules:
            msg = "a BLOCK verdict must name the rule(s) it violated"
            raise ValueError(msg)
        return self
