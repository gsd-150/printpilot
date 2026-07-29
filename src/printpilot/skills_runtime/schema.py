"""What a Skill declares about itself.

A Skill is not a document and not a retrieved passage. RAG supplies facts, a Tool
supplies an action, and a Skill supplies **a procedure** — including the part that
is hardest to capture anywhere else: what would rule this out. The
``## 排除项`` section is mandatory for exactly that reason.

The input model is split three ways because a single ``inputs`` list turned out to
be wrong. Filtering a Skill out whenever any declared input is missing removes the
*right* Skill precisely when a sensor has dropped — which is when its judgement
about ambiguity is most needed. So:

* ``required_inputs`` — without these the Skill cannot say anything; it is excluded.
* ``optional_inputs`` — sharpen the conclusion; missing ones lower confidence.
* ``missing_input_policy`` — what to do about the latter.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

DESCRIPTION_MIN = 40
DESCRIPTION_MAX = 500


class MissingInputPolicy(StrEnum):
    DEGRADE_WITH_LOWER_CONFIDENCE = "degrade_with_lower_confidence"
    EXCLUDE = "exclude"


class SkillMeta(BaseModel):
    """Parsed ``SKILL.md`` frontmatter."""

    # `coerce_numbers_to_str` so that a version written as bare `1.0` — which YAML
    # reads as a float — reaches R2 and is reported as "not semver", rather than
    # dying here with a type error that says nothing about the actual problem.
    model_config = ConfigDict(extra="forbid", frozen=True, coerce_numbers_to_str=True)

    name: str
    description: str = Field(
        description=(
            "States the *trigger conditions*, not a summary of the contents. "
            "Routing reads this; 'this skill detects clogs' matches far worse than "
            "'when flow falls while extruder current rises'."
        )
    )
    version: str
    domain: str
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    missing_input_policy: MissingInputPolicy = MissingInputPolicy.DEGRADE_WITH_LOWER_CONFIDENCE
    minimum_evidence_count: int = Field(default=1, ge=1)
    tags: tuple[str, ...] = ()

    @property
    def all_inputs(self) -> tuple[str, ...]:
        return self.required_inputs + self.optional_inputs


class Skill(BaseModel):
    """Frontmatter plus body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: SkillMeta
    body: str
    source: str = Field(description="Path relative to the skills root, for traceability.")

    @property
    def name(self) -> str:
        return self.meta.name


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str
    severity: Severity
    skill: str
    message: str

    def __str__(self) -> str:
        mark = "ERROR" if self.severity is Severity.ERROR else "WARN "
        return f"{mark} [{self.rule}] {self.skill}: {self.message}"
