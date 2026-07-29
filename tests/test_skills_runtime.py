"""Skill loading, registration rules, and routing.

Two tests carry most of the weight:

* ``test_r3_rejects_an_input_perception_cannot_produce`` — a Skill written against
  a feature that does not exist reads perfectly in review and never fires. Only a
  machine check catches it.
* ``test_a_blinded_case_still_routes_the_skill_that_knows_to_abstain`` — the
  degradation path. Filtering on all declared inputs would drop the triage Skill
  exactly when a sensor is missing, which is when its advice about ambiguity
  matters most.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printpilot.domain import PhenomenonReport, SignalFeature
from printpilot.perception import NOMINAL_BANDS
from printpilot.skills_runtime import (
    MissingInputPolicy,
    Severity,
    SkillParseError,
    SkillRegistry,
    parse_skill,
)
from printpilot.skills_runtime.loader import scan, scan_tolerant
from printpilot.skills_runtime.registry import EXCLUSIONS_PATTERN

BAD_SKILLS = Path(__file__).parent / "fixtures" / "bad_skills"

GOOD_FRONTMATTER = """---
name: sample-skill
description: >
  当 flow_tail_mean 低于正常带且 current_delta 上升时使用，用于判断挤出阻力是否
  真的增大，并说明何种情况下不应作此判断。
version: 1.2.3
domain: fdm/test
required_inputs: [flow_tail_mean]
optional_inputs: [current_delta]
triggers: [flow_tail_mean, current_delta]
minimum_evidence_count: 1
---

# 示例

## 排除项

- 电流正常时不成立。
"""


def _report(exceeded: list[str], present: list[str] | None = None) -> PhenomenonReport:
    """A report where the named features are present, some out of band."""
    names = present if present is not None else exceeded
    return PhenomenonReport(
        case_id="t-1",
        material="PLA",
        features=[
            SignalFeature(
                name=name,
                value=0.5,
                unit="ratio",
                threshold=1.0,
                exceeded=name in exceeded,
            )
            for name in names
        ],
        uncomputable_features=sorted(set(NOMINAL_BANDS) - set(names)),
    )


class TestParsing:
    def test_reads_yaml_frontmatter_with_lists(self) -> None:
        skill = parse_skill(GOOD_FRONTMATTER, source="sample-skill/SKILL.md")
        assert skill.name == "sample-skill"
        assert skill.meta.required_inputs == ("flow_tail_mean",)
        assert skill.meta.triggers == ("flow_tail_mean", "current_delta")
        assert "排除项" in skill.body

    def test_version_written_as_a_bare_number_survives_parsing(self) -> None:
        """YAML reads `1.0` as a float. It has to reach R2 to be reported as
        'not semver', rather than dying with a type error that explains nothing."""
        text = GOOD_FRONTMATTER.replace("version: 1.2.3", "version: 1.0")
        assert parse_skill(text, source="s/SKILL.md").meta.version == "1.0"

    def test_missing_frontmatter(self) -> None:
        with pytest.raises(SkillParseError, match="no frontmatter"):
            parse_skill("# just a body", source="s/SKILL.md")

    def test_empty_body(self) -> None:
        """Valid frontmatter, no procedure. The frontmatter has to be complete or
        the schema check fires first and this rule is never reached."""
        head = GOOD_FRONTMATTER.split("---", 2)[1]
        with pytest.raises(SkillParseError, match="body is empty"):
            parse_skill(f"---{head}---\n   \n", source="s/SKILL.md")

    def test_frontmatter_that_is_not_a_mapping(self) -> None:
        with pytest.raises(SkillParseError, match="must be a mapping"):
            parse_skill("---\n- a\n- b\n---\nbody", source="s/SKILL.md")

    def test_unknown_frontmatter_key_is_rejected(self) -> None:
        text = GOOD_FRONTMATTER.replace("domain: fdm/test", "domain: fdm/test\ninvented: 1")
        with pytest.raises(SkillParseError, match="does not match the Skill schema"):
            parse_skill(text, source="s/SKILL.md")


class TestTolerantScan:
    def test_reports_bad_files_instead_of_stopping(self) -> None:
        """A validation tool that dies on the first malformed input reports one
        problem per run and hides the rest behind it."""
        skills, failures = scan_tolerant(BAD_SKILLS)
        assert {s.name for s in skills} == {"Bad_Name", "no-exclusions", "unknown-input"}
        assert [Path(source).parent.name for source, _ in failures] == ["unparseable"]

    def test_strict_scan_still_raises(self) -> None:
        with pytest.raises(SkillParseError):
            scan(BAD_SKILLS)

    def test_a_missing_directory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert scan_tolerant(tmp_path / "nope") == ([], [])


@pytest.fixture(scope="class")
def bad() -> SkillRegistry:
    return SkillRegistry.load(BAD_SKILLS)


class TestRegistrationRules:
    def _rules(self, registry: SkillRegistry) -> set[str]:
        return {i.rule for i in registry.validate() if i.severity is Severity.ERROR}

    def test_the_shipped_skills_pass(self) -> None:
        registry = SkillRegistry.load()
        assert registry.skills, "no skills found; the registry is pointing somewhere wrong"
        assert registry.errors == []

    def test_r0_reports_unparseable_files(self, bad: SkillRegistry) -> None:
        assert "R0" in self._rules(bad)

    def test_r1_rejects_a_non_kebab_name(self, bad: SkillRegistry) -> None:
        assert "R1" in self._rules(bad)

    def test_r2_rejects_a_non_semver_version(self, bad: SkillRegistry) -> None:
        assert "R2" in self._rules(bad)

    def test_r3_rejects_an_input_perception_cannot_produce(self, bad: SkillRegistry) -> None:
        """The rule that earns its place. Such a Skill reads well and never fires."""
        message = next(i for i in bad.validate() if i.rule == "R3").message
        assert "nozzle_vibration_rms" in message
        assert "perception never produces" in message

    def test_r3_rejects_a_skill_with_no_triggers(self) -> None:
        text = GOOD_FRONTMATTER.replace("triggers: [flow_tail_mean, current_delta]", "triggers: []")
        registry = SkillRegistry(skills=[parse_skill(text, source="s/SKILL.md")])
        assert any("no triggers" in i.message for i in registry.validate())

    def test_r4_flags_a_description_that_names_no_trigger(self) -> None:
        text = GOOD_FRONTMATTER.replace(
            "当 flow_tail_mean 低于正常带且 current_delta 上升时使用，用于判断挤出阻力是否\n"
            "  真的增大，并说明何种情况下不应作此判断。",
            "本技能用于检测挤出系统的各类异常状况，涵盖多种常见故障模式的识别与处理。",
        )
        registry = SkillRegistry(skills=[parse_skill(text, source="s/SKILL.md")])
        assert any(i.rule == "R4" for i in registry.validate())

    def test_r5_requires_an_exclusions_heading(self, bad: SkillRegistry) -> None:
        assert "R5" in self._rules(bad)

    def test_r5_matches_a_heading_not_a_passing_mention(self) -> None:
        """Substring matching was the first attempt, and a fixture whose *title*
        said it lacked the section passed it."""
        assert not EXCLUSIONS_PATTERN.search("本文没有排除项这一节")
        assert EXCLUSIONS_PATTERN.search("## 排除项\n\n- 某条")

    def test_r6_warns_on_near_duplicate_descriptions(self) -> None:
        a = parse_skill(GOOD_FRONTMATTER, source="a/SKILL.md")
        b = parse_skill(
            GOOD_FRONTMATTER.replace("sample-skill", "sample-skill-2"), source="b/SKILL.md"
        )
        issues = SkillRegistry(skills=[a, b]).validate()
        assert any(i.rule == "R6" and i.severity is Severity.WARNING for i in issues)

    def test_warnings_alone_do_not_count_as_errors(self) -> None:
        """Only errors should fail CI; a duplicate-description warning should not."""
        a = parse_skill(GOOD_FRONTMATTER, source="a/SKILL.md")
        b = parse_skill(
            GOOD_FRONTMATTER.replace("sample-skill", "sample-skill-2"), source="b/SKILL.md"
        )
        assert SkillRegistry(skills=[a, b]).errors == []


@pytest.fixture(scope="class")
def registry() -> SkillRegistry:
    return SkillRegistry.load()


class TestRouting:
    def test_healthy_prints_select_nothing(self, registry: SkillRegistry) -> None:
        """No feature out of band means no procedure applies. Routing must not fire
        on a good print just because the signals are available."""
        assert registry.route(_report(exceeded=[], present=list(NOMINAL_BANDS))) == []

    def test_extrusion_anomaly_ranks_first_on_a_clog_signature(
        self, registry: SkillRegistry
    ) -> None:
        matches = registry.route(
            _report(
                exceeded=["flow_tail_mean", "flow_tail_deficit_fraction", "current_delta"],
                present=list(NOMINAL_BANDS),
            )
        )
        assert matches[0].skill.name == "extrusion-anomaly-triage"
        assert matches[0].score == pytest.approx(1.0)
        assert not matches[0].degraded

    def test_a_blinded_case_still_routes_the_skill_that_knows_to_abstain(
        self, registry: SkillRegistry
    ) -> None:
        """The whole point of splitting required from optional inputs.

        With ``current_delta`` gone, clog and parameter fault are indistinguishable
        — which is precisely when the Skill's advice to abstain is needed. Filtering
        on all declared inputs would have dropped it here.
        """
        present = [n for n in NOMINAL_BANDS if not n.startswith("current_")]
        matches = registry.route(
            _report(exceeded=["flow_tail_mean", "flow_tail_deficit_fraction"], present=present)
        )
        triage = next(m for m in matches if m.skill.name == "extrusion-anomaly-triage")
        assert triage.degraded
        assert "current_delta" in triage.missing_optional

    def test_degradation_lowers_the_score(self, registry: SkillRegistry) -> None:
        full = registry.route(
            _report(
                exceeded=["flow_tail_mean", "flow_tail_deficit_fraction"],
                present=list(NOMINAL_BANDS),
            )
        )
        blinded = registry.route(
            _report(
                exceeded=["flow_tail_mean", "flow_tail_deficit_fraction"],
                present=[n for n in NOMINAL_BANDS if not n.startswith("current_")],
            )
        )
        assert blinded[0].score < full[0].score

    def test_a_missing_required_input_excludes_the_skill(self) -> None:
        text = GOOD_FRONTMATTER.replace(
            "required_inputs: [flow_tail_mean]", "required_inputs: [temp_deviation_tail]"
        )
        registry = SkillRegistry(skills=[parse_skill(text, source="s/SKILL.md")])
        assert registry.route(_report(exceeded=["flow_tail_mean"])) == []

    def test_exclude_policy_drops_the_skill_when_an_optional_input_is_missing(self) -> None:
        text = GOOD_FRONTMATTER.replace(
            "minimum_evidence_count: 1",
            f"missing_input_policy: {MissingInputPolicy.EXCLUDE.value}",
        )
        registry = SkillRegistry(skills=[parse_skill(text, source="s/SKILL.md")])
        assert registry.route(_report(exceeded=["flow_tail_mean"])) == []

    def test_minimum_evidence_count_is_enforced(self) -> None:
        text = GOOD_FRONTMATTER.replace("minimum_evidence_count: 1", "minimum_evidence_count: 2")
        registry = SkillRegistry(skills=[parse_skill(text, source="s/SKILL.md")])
        assert registry.route(_report(exceeded=["flow_tail_mean"])) == []
        assert registry.route(_report(exceeded=["flow_tail_mean", "current_delta"]))

    def test_top_k_is_respected(self, registry: SkillRegistry) -> None:
        matches = registry.route(_report(exceeded=list(NOMINAL_BANDS)), top_k=1)
        assert len(matches) == 1

    def test_ordering_is_stable_for_equal_scores(self, registry: SkillRegistry) -> None:
        report = _report(exceeded=["flow_tail_mean", "current_delta", "temp_deviation_tail"])
        first = [m.skill.name for m in registry.route(report)]
        assert first == [m.skill.name for m in registry.route(report)]
