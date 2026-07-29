"""Prompt loading, and the constraints on the baseline prompt itself.

The last group is unusual but load-bearing: it asserts that the baseline prompt
does **not** contain the domain heuristics. If those leak into the control arm,
the `+RAG` and `+Skills` configurations have nothing left to contribute and the
ablation silently stops measuring anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printpilot.diagnosis.llm import DEFAULT_PROMPT, render_phenomenon
from printpilot.domain import PhenomenonReport, SignalFeature
from printpilot.prompts import PROMPTS_ROOT, PromptError, load_prompt, parse_prompt


class TestParsing:
    def test_reads_frontmatter_and_body(self) -> None:
        prompt = parse_prompt("t", "---\nversion: 3\nparent: v2\n---\nBody {x}")
        assert prompt.version == "3"
        assert prompt.metadata["parent"] == "v2"
        assert prompt.template == "Body {x}"

    def test_rejects_a_file_without_frontmatter(self) -> None:
        with pytest.raises(PromptError, match="no frontmatter"):
            parse_prompt("t", "just a body")

    def test_rejects_a_prompt_without_a_version(self) -> None:
        """An unversioned prompt cannot be tied to the eval report that justified it."""
        with pytest.raises(PromptError, match="does not declare a version"):
            parse_prompt("t", "---\nparent: v1\n---\nbody")

    def test_render_substitutes_placeholders(self) -> None:
        prompt = parse_prompt("t", "---\nversion: 1\n---\nCase: {phenomenon}")
        assert prompt.render(phenomenon="X") == "Case: X"

    def test_missing_placeholder_is_an_error_not_a_silent_gap(self) -> None:
        prompt = parse_prompt("t", "---\nversion: 1\n---\n{phenomenon}")
        with pytest.raises(PromptError, match="placeholder"):
            prompt.render(other="X")

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PromptError, match="no prompt at"):
            load_prompt("nope", root=tmp_path)


class TestPhenomenonRendering:
    def _report(self, **kwargs: object) -> PhenomenonReport:
        base: dict[str, object] = {
            "case_id": "dev-0001",
            "material": "PLA",
            "features": [
                SignalFeature(
                    name="flow_tail_mean",
                    value=0.81,
                    unit="ratio",
                    threshold=0.985,
                    exceeded=True,
                )
            ],
        }
        base.update(kwargs)
        return PhenomenonReport.model_validate(base)

    def test_includes_value_and_band(self) -> None:
        text = render_phenomenon(self._report())
        assert "flow_tail_mean" in text
        assert "0.8100" in text
        assert "outside nominal" in text

    def test_states_that_unmeasured_is_not_normal(self) -> None:
        """The distinction abstention depends on."""
        text = render_phenomenon(
            self._report(
                missing_signals=["extruder_current"],
                uncomputable_features=["current_delta", "current_mean"],
            )
        )
        assert "could NOT be measured" in text
        assert "absent, not normal" in text

    def test_carries_no_case_metadata(self) -> None:
        """No family id, no split, no label — nothing that encodes the answer."""
        text = render_phenomenon(self._report())
        for leaked in ("family", "split", "CLOG", "UNDEREXT", "THERMAL", "remediation"):
            assert leaked not in text


DIAGNOSIS_PROMPTS = sorted(
    p.stem for p in (PROMPTS_ROOT / "diagnosis").glob("*.md") if p.stem != "CHANGELOG"
)

#: Words that would give away *which signal discriminates which fault*. That
#: knowledge is what the `+RAG` and `+Skills` configurations exist to supply; in
#: the control arm it would make their contribution unmeasurable.
LEAKED_HEURISTICS = (
    "resistance",
    "restriction",
    "mechanical",
    "back pressure",
    "grind",
    "cold pull",
    "flow rate setting",
    "extruder current rises",
)


class TestEveryDiagnosisPromptStaysKnowledgeMinimal:
    """Applies to **all** versions, not just the default.

    Prompt iteration is where domain hints creep in: it is tempting to fix a
    failing case by telling the model the answer. Every revision has to pass this,
    so an improvement that works by leaking knowledge fails the build instead of
    quietly hollowing out the ablation.
    """

    @pytest.mark.parametrize("name", DIAGNOSIS_PROMPTS)
    @pytest.mark.parametrize("heuristic", LEAKED_HEURISTICS)
    def test_no_discrimination_heuristic_is_stated(self, name: str, heuristic: str) -> None:
        text = load_prompt(f"diagnosis/{name}").template.lower()
        assert heuristic not in text, (
            f"prompt {name!r} mentions {heuristic!r}; that knowledge belongs to the "
            "layers being ablated, not to the control arm"
        )

    @pytest.mark.parametrize("name", DIAGNOSIS_PROMPTS)
    def test_it_still_lists_the_valid_fault_codes(self, name: str) -> None:
        """Knowledge-minimal, not task-free: the model must know the label set."""
        text = load_prompt(f"diagnosis/{name}").template.lower()
        for code in ("clog_partial", "clog_full", "underext_param", "unknown"):
            assert code in text

    @pytest.mark.parametrize("name", DIAGNOSIS_PROMPTS)
    def test_it_requires_evidence(self, name: str) -> None:
        text = load_prompt(f"diagnosis/{name}").template.lower()
        assert "cite evidence" in text

    @pytest.mark.parametrize("name", DIAGNOSIS_PROMPTS)
    def test_it_offers_a_way_out(self, name: str) -> None:
        """Abstention has to be reachable, or the UNKNOWN metrics measure nothing."""
        text = load_prompt(f"diagnosis/{name}").template.lower()
        assert "abstain" in text or "unknown" in text

    def test_the_default_prompt_exists(self) -> None:
        assert DEFAULT_PROMPT.split("/", 1)[1] in DIAGNOSIS_PROMPTS

    def test_versions_are_unique(self) -> None:
        versions = [load_prompt(f"diagnosis/{n}").version for n in DIAGNOSIS_PROMPTS]
        assert len(versions) == len(set(versions))
