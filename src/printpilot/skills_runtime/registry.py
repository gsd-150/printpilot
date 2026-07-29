"""The Skills registry: validation at registration, routing at call time.

**Validation** runs in CI. The rule that earns its place is R3: a Skill may only
declare inputs that perception can actually produce. Without it, a Skill can be
written against a feature that does not exist, pass review because the prose reads
well, and then silently never fire.

**Routing** is deliberately deterministic here. The plan called for semantic
ranking over descriptions, which needs the embedding store landing in M6; ranking
by lexical overlap in the meantime would be a worse method wearing the same name.
So a Skill declares ``triggers`` — feature names — and routing scores how many of
them are actually out of band on this case. When M6 lands, embedding-based routing
becomes a second method to compare against this one rather than a replacement
assumed to be better.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from printpilot.domain import PhenomenonReport
from printpilot.perception import NOMINAL_BANDS
from printpilot.skills_runtime.loader import scan_tolerant
from printpilot.skills_runtime.schema import (
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    KEBAB,
    SEMVER,
    MissingInputPolicy,
    Severity,
    Skill,
    ValidationIssue,
)

#: Above this description similarity, two Skills are probably the same Skill.
DUPLICATE_THRESHOLD = 0.85

#: Confidence multiplier applied per missing optional input.
DEGRADE_FACTOR = 0.75

EXCLUSIONS_HEADING = "排除项"
EXCLUSIONS_PATTERN = re.compile(rf"^#{{1,6}}\s.*{EXCLUSIONS_HEADING}", re.MULTILINE)


@dataclass(frozen=True)
class RouteMatch:
    skill: Skill
    score: float
    satisfied_triggers: tuple[str, ...]
    missing_optional: tuple[str, ...]

    @property
    def degraded(self) -> bool:
        return bool(self.missing_optional)


@dataclass
class SkillRegistry:
    skills: list[Skill] = field(default_factory=list)
    #: ``(source, error)`` for files that would not parse. Kept rather than raised
    #: so ``validate`` can report them alongside everything else.
    parse_failures: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path | None = None) -> SkillRegistry:
        skills, failures = scan_tolerant(root)
        return cls(skills=skills, parse_failures=failures)

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.skills if s.name == name), None)

    # ------------------------------------------------------------------ validate

    def validate(self) -> list[ValidationIssue]:
        """Every registration rule, run over the whole registry.

        Returns issues rather than raising: ``skills validate`` reports all of them
        at once, and fixing one problem per CI run is a bad way to spend a day.
        """
        issues: list[ValidationIssue] = [
            ValidationIssue(
                rule="R0",
                severity=Severity.ERROR,
                skill=source,
                message=f"could not be parsed: {error}",
            )
            for source, error in self.parse_failures
        ]
        issues += self._r1_names()
        issues += self._r2_versions()
        issues += self._r3_inputs_exist()
        issues += self._r4_description_states_triggers()
        issues += self._r5_body_has_exclusions()
        issues += self._r6_near_duplicates()
        return issues

    def _r1_names(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        seen: dict[str, str] = {}
        for skill in self.skills:
            if not KEBAB.match(skill.name):
                issues.append(
                    ValidationIssue(
                        rule="R1",
                        severity=Severity.ERROR,
                        skill=skill.name,
                        message="name must be kebab-case",
                    )
                )
            if skill.name in seen:
                issues.append(
                    ValidationIssue(
                        rule="R1",
                        severity=Severity.ERROR,
                        skill=skill.name,
                        message=f"duplicate name, already defined by {seen[skill.name]}",
                    )
                )
            seen[skill.name] = skill.source

            directory = Path(skill.source).parent.name
            if directory and directory != skill.name:
                issues.append(
                    ValidationIssue(
                        rule="R1",
                        severity=Severity.WARNING,
                        skill=skill.name,
                        message=f"directory {directory!r} does not match the name",
                    )
                )
        return issues

    def _r2_versions(self) -> list[ValidationIssue]:
        return [
            ValidationIssue(
                rule="R2",
                severity=Severity.ERROR,
                skill=s.name,
                message=f"version {s.meta.version!r} is not semver",
            )
            for s in self.skills
            if not SEMVER.match(s.meta.version)
        ]

    def _r3_inputs_exist(self) -> list[ValidationIssue]:
        """A Skill may only declare features perception can actually produce.

        This is the rule worth having. Without it a Skill can name a feature that
        does not exist, read perfectly well in review, and never fire.
        """
        known = set(NOMINAL_BANDS)
        issues: list[ValidationIssue] = []
        for skill in self.skills:
            declared = set(skill.meta.all_inputs) | set(skill.meta.triggers)
            for unknown in sorted(declared - known):
                issues.append(
                    ValidationIssue(
                        rule="R3",
                        severity=Severity.ERROR,
                        skill=skill.name,
                        message=(
                            f"declares {unknown!r}, which perception never produces; "
                            f"known features: {', '.join(sorted(known))}"
                        ),
                    )
                )
            if not skill.meta.triggers:
                issues.append(
                    ValidationIssue(
                        rule="R3",
                        severity=Severity.ERROR,
                        skill=skill.name,
                        message="declares no triggers, so routing can never select it",
                    )
                )
        return issues

    def _r4_description_states_triggers(self) -> list[ValidationIssue]:
        """Routing reads the description, so it must describe *when* to use the
        Skill. Length alone is a weak proxy, so it must also mention at least one
        of the features it claims to trigger on."""
        issues: list[ValidationIssue] = []
        for skill in self.skills:
            text = skill.meta.description
            if not DESCRIPTION_MIN <= len(text) <= DESCRIPTION_MAX:
                issues.append(
                    ValidationIssue(
                        rule="R4",
                        severity=Severity.ERROR,
                        skill=skill.name,
                        message=(
                            f"description is {len(text)} chars, expected "
                            f"{DESCRIPTION_MIN}-{DESCRIPTION_MAX}"
                        ),
                    )
                )
            if skill.meta.triggers and not any(t in text for t in skill.meta.triggers):
                issues.append(
                    ValidationIssue(
                        rule="R4",
                        severity=Severity.WARNING,
                        skill=skill.name,
                        message=(
                            "description names none of its trigger features; it likely "
                            "summarises the contents instead of stating when to apply it"
                        ),
                    )
                )
        return issues

    def _r5_body_has_exclusions(self) -> list[ValidationIssue]:
        """The section that distinguishes a Skill from a retrieved passage.

        Matched as a *heading*, not as a substring. Substring matching was the first
        attempt and a fixture titled "the skill that lacks 排除项" passed it — the
        words appeared, the section did not.
        """
        return [
            ValidationIssue(
                rule="R5",
                severity=Severity.ERROR,
                skill=s.name,
                message=(
                    f"body has no '{EXCLUSIONS_HEADING}' heading; without it this is "
                    "a document, not a procedure"
                ),
            )
            for s in self.skills
            if not EXCLUSIONS_PATTERN.search(s.body)
        ]

    def _r6_near_duplicates(self) -> list[ValidationIssue]:
        """Two Skills describing the same trigger will split routing between them."""
        issues: list[ValidationIssue] = []
        for i, a in enumerate(self.skills):
            for b in self.skills[i + 1 :]:
                ratio = SequenceMatcher(None, a.meta.description, b.meta.description).ratio()
                if ratio > DUPLICATE_THRESHOLD:
                    issues.append(
                        ValidationIssue(
                            rule="R6",
                            severity=Severity.WARNING,
                            skill=a.name,
                            message=f"description is {ratio:.0%} similar to {b.name}",
                        )
                    )
        return issues

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.validate() if i.severity is Severity.ERROR]

    # --------------------------------------------------------------------- route

    def route(self, report: PhenomenonReport, top_k: int = 3) -> list[RouteMatch]:
        """Select the Skills worth putting in front of the model.

        Stage 1 is a hard filter on ``required_inputs``: no measurement, no opinion.
        Stage 2 scores how much of what the Skill triggers on is actually anomalous
        here, so a Skill about extrusion does not get loaded for a purely thermal
        case just because its inputs happen to be available.
        """
        available = {f.name for f in report.features}
        exceeded = {f.name for f in report.features if f.exceeded}

        matches: list[RouteMatch] = []
        for skill in self.skills:
            meta = skill.meta
            if not set(meta.required_inputs) <= available:
                continue

            missing_optional = tuple(sorted(set(meta.optional_inputs) - available))
            if missing_optional and meta.missing_input_policy is MissingInputPolicy.EXCLUDE:
                continue

            satisfied = tuple(t for t in meta.triggers if t in exceeded)
            if len(satisfied) < meta.minimum_evidence_count:
                continue

            score = len(satisfied) / len(meta.triggers) if meta.triggers else 0.0
            score *= DEGRADE_FACTOR ** len(missing_optional)
            matches.append(
                RouteMatch(
                    skill=skill,
                    score=score,
                    satisfied_triggers=satisfied,
                    missing_optional=missing_optional,
                )
            )

        matches.sort(key=lambda m: (-m.score, m.skill.name))
        return matches[:top_k]
