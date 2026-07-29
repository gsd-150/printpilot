"""The LLM diagnoser and the Skills injection path.

The invariant worth protecting: the ``llm`` and ``llm+skills`` arms differ by
**exactly one thing**. Same prompt file, same model, same rendering of the case —
only the appended Skills block differs. A second template would let wording drift
between the arms and quietly become a second variable, at which point the ablation
stops attributing anything.
"""

from __future__ import annotations

import pytest

from printpilot.diagnosis.llm import LLMDiagnoser, phenomenon_query, render_skills
from printpilot.domain import (
    DiagnosisResult,
    EvidenceKind,
    EvidenceRef,
    FaultCode,
    Hypothesis,
    PhenomenonReport,
    SignalFeature,
)
from printpilot.harness import Step, Tracer
from printpilot.llm import LLMError, MockLLMClient
from printpilot.perception import NOMINAL_BANDS
from printpilot.rag import DeterministicEmbedder, KnowledgeStore, load_cards
from printpilot.skills_runtime import SkillRegistry


def _report(exceeded: list[str], uncomputable: list[str] | None = None) -> PhenomenonReport:
    present = [n for n in NOMINAL_BANDS if n not in (uncomputable or [])]
    return PhenomenonReport(
        case_id="dev-0001",
        material="PLA",
        features=[
            SignalFeature(
                name=name, value=0.5, unit="ratio", threshold=1.0, exceeded=name in exceeded
            )
            for name in present
        ],
        uncomputable_features=sorted(uncomputable or []),
    )


def _answer(fault: FaultCode = FaultCode.CLOG_PARTIAL) -> DiagnosisResult:
    return DiagnosisResult(
        case_id="dev-0001",
        hypotheses=[
            Hypothesis(
                fault_code=fault,
                confidence=0.8,
                reasoning="示例。",
                evidence=[EvidenceRef(kind=EvidenceKind.SIGNAL, ref="flow_tail_mean")],
            )
        ],
    )


@pytest.fixture
def registry() -> SkillRegistry:
    return SkillRegistry.load()


class TestAblationHygiene:
    def test_both_arms_share_one_prompt_file(self, registry: SkillRegistry) -> None:
        plain = LLMDiagnoser(client=MockLLMClient(scripted=[_answer()]))
        with_skills = LLMDiagnoser(client=MockLLMClient(scripted=[_answer()]), skills=registry)
        assert plain.prompt.name == with_skills.prompt.name
        assert plain.prompt.template == with_skills.prompt.template

    def test_the_skills_block_is_the_only_difference(self, registry: SkillRegistry) -> None:
        report = _report(exceeded=["flow_tail_mean", "current_delta"])

        plain_client = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=plain_client)(report)

        skilled_client = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=skilled_client, skills=registry)(report)

        plain_prompt = plain_client.calls[0].prompt
        skilled_prompt = skilled_client.calls[0].prompt
        assert skilled_prompt.startswith(plain_prompt), (
            "the skilled arm must be the plain prompt plus an appended block, "
            "not a separately worded template"
        )

    def test_arm_names_are_distinguishable_in_reports(self, registry: SkillRegistry) -> None:
        assert LLMDiagnoser(client=MockLLMClient()).name.startswith("llm@")
        assert LLMDiagnoser(client=MockLLMClient(), skills=registry).name.startswith("llm+skills@")


class TestSkillInjection:
    def test_a_matching_skill_reaches_the_prompt(self, registry: SkillRegistry) -> None:
        client = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=client, skills=registry)(
            _report(exceeded=["flow_tail_mean", "current_delta"])
        )
        prompt = client.calls[0].prompt
        assert "extrusion-anomaly-triage" in prompt
        assert "排除项" in prompt

    def test_a_healthy_case_injects_nothing(self, registry: SkillRegistry) -> None:
        """No feature out of band means no procedure applies, and paying for a
        Skill block on a good print is waste."""
        client = MockLLMClient(scripted=[_answer(FaultCode.NORMAL_SUSPICIOUS)])
        LLMDiagnoser(client=client, skills=registry)(_report(exceeded=[]))
        assert "适用的领域技能" not in client.calls[0].prompt

    def test_degraded_selection_says_so_in_the_prompt(self, registry: SkillRegistry) -> None:
        """A Skill advising on a case it can only partly see must announce that."""
        client = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=client, skills=registry)(
            _report(
                exceeded=["flow_tail_mean", "flow_tail_deficit_fraction"],
                uncomputable=["current_delta", "current_mean"],
            )
        )
        prompt = client.calls[0].prompt
        assert "降级" in prompt
        assert "current_delta" in prompt

    def test_top_k_bounds_what_is_injected(self, registry: SkillRegistry) -> None:
        client = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=client, skills=registry, top_k=1)(_report(exceeded=list(NOMINAL_BANDS)))
        assert client.calls[0].prompt.count("## safe-action-selection") == 0

    def test_skills_used_records_what_was_injected(self, registry: SkillRegistry) -> None:
        """From the injection, not from the model's claim about itself."""
        result = LLMDiagnoser(client=MockLLMClient(scripted=[_answer()]), skills=registry)(
            _report(exceeded=["flow_tail_mean", "current_delta"])
        )
        assert "extrusion-anomaly-triage" in result.skills_used

    def test_render_skills_is_empty_without_matches(self) -> None:
        assert render_skills([]) == ""


@pytest.fixture(scope="class")
def store() -> KnowledgeStore:
    built = KnowledgeStore(embedder=DeterministicEmbedder())
    built.build(load_cards())
    return built


class TestKnowledgeInjection:
    def test_retrieved_passages_reach_the_prompt_with_provenance(
        self, store: KnowledgeStore
    ) -> None:
        """A passage without its evidence level cannot be placed in the priority
        chain, so citing it is part of injecting it."""
        client = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=client, knowledge=store)(_report(exceeded=["flow_tail_mean"]))
        prompt = client.calls[0].prompt
        assert "检索到的知识" in prompt
        assert "来源：" in prompt
        assert "优先级低于经审核的 Skill" in prompt

    def test_the_rag_block_is_appended_to_the_same_base_prompt(self, store: KnowledgeStore) -> None:
        report = _report(exceeded=["flow_tail_mean"])
        plain = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=plain)(report)
        with_rag = MockLLMClient(scripted=[_answer()])
        LLMDiagnoser(client=with_rag, knowledge=store)(report)
        assert with_rag.calls[0].prompt.startswith(plain.calls[0].prompt)

    def test_retrieved_ids_are_recorded(self, store: KnowledgeStore) -> None:
        result = LLMDiagnoser(client=MockLLMClient(scripted=[_answer()]), knowledge=store)(
            _report(exceeded=["flow_tail_mean"])
        )
        assert result.retrieved_chunk_ids

    def test_the_query_is_built_from_anomalies_and_blind_spots(self) -> None:
        """Only what is out of band, plus what could not be measured. Querying with
        every feature would return the whole corpus."""
        query = phenomenon_query(
            _report(exceeded=["flow_tail_mean"], uncomputable=["current_delta"])
        )
        assert "流量" in query
        assert "current_delta" in query
        assert "温度" not in query

    def test_the_query_uses_the_corpus_vocabulary_not_identifiers(self) -> None:
        """The first version emitted `flow_tail_mean 0.810` — the variable name and
        its value. The corpus is prose, and a variable name is not what prose calls
        a thing; retrieval was measurably worse for it."""
        query = phenomenon_query(_report(exceeded=["current_delta"]))
        assert "挤出机电流" in query
        assert "current_delta" not in query

    def test_arm_names_distinguish_every_combination(self, store: KnowledgeStore) -> None:
        registry = SkillRegistry.load()
        assert LLMDiagnoser(client=MockLLMClient(), knowledge=store).name.startswith("llm+rag@")
        assert LLMDiagnoser(
            client=MockLLMClient(), knowledge=store, skills=registry
        ).name.startswith("llm+rag+skills@")

    def test_tracing_records_retrieval_and_diagnosis(self, store: KnowledgeStore) -> None:
        tracer = Tracer()
        LLMDiagnoser(client=MockLLMClient(scripted=[_answer()]), knowledge=store, tracer=tracer)(
            _report(exceeded=["flow_tail_mean"])
        )
        steps = {e.step for e in tracer.events}
        assert {Step.RETRIEVAL, Step.DIAGNOSIS} <= steps


class TestFailureHandling:
    def test_a_transport_failure_abstains_rather_than_guesses(self) -> None:
        """Network behaviour must not be scored as a diagnosis."""
        diagnoser = LLMDiagnoser(client=MockLLMClient(raises=LLMError("timeout")))
        result = diagnoser(_report(exceeded=["flow_tail_mean"]))
        assert result.top.fault_code is FaultCode.UNKNOWN
        assert result.top.confidence == 0.0
        assert diagnoser.failures == 1

    def test_an_echoed_case_id_is_corrected(self) -> None:
        answer = DiagnosisResult(
            case_id="probe-1",
            hypotheses=[Hypothesis(fault_code=FaultCode.UNKNOWN, confidence=0.4, reasoning="x")],
        )
        result = LLMDiagnoser(client=MockLLMClient(scripted=[answer]))(
            _report(exceeded=["flow_tail_mean"])
        )
        assert result.case_id == "dev-0001"
