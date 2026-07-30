"""Reflection: the only node that writes knowledge, and only into quarantine.

The property these tests defend is structural rather than behavioural: nothing
the model returns can reach ``knowledge/accepted/``. A prompt rule can be
ignored by a model; a write path that does not exist cannot be.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import printpilot.reflection.agent as agent_module
from printpilot.domain import FaultCode
from printpilot.llm import MockLLMClient
from printpilot.llm.base import LLMError
from printpilot.loop import LoopResult, run_round
from printpilot.rag.cards import CANDIDATE, EvidenceLevel, load_cards
from printpilot.reflection import CandidateDraft, Reflector, render_round, write_candidate
from printpilot.simulator import Material, NoiseProfile, ScenarioFamily
from printpilot.simulator.scenario import Geometry


def _round(fault: FaultCode = FaultCode.UNDEREXT_PARAM, seed: str = "s0") -> LoopResult:
    family = ScenarioFamily(
        fault=fault, material=Material.PLA, geometry=Geometry.BOX, noise=NoiseProfile.NOMINAL
    )
    return run_round(family, case_id=f"demo-{fault.value}", seed=seed)


def _draft() -> CandidateDraft:
    return CandidateDraft(
        title="尾段欠挤出小步提升 flow 后质量回升",
        body=(
            "现象：尾段流量比持续低于正常带。\n\n"
            "判断与动作：诊断为参数性欠挤出，提议小步上调 flow。\n\n"
            "门禁裁决：放行。\n\n"
            "测得结果：独立质量分回升。\n\n"
            "局限：单一合成案例，分数来自仿真。"
        ),
        tags=("underextrusion", "flow"),
    )


class TestRenderRound:
    def test_contains_the_observable_record(self) -> None:
        result = _round()
        text = render_round(result)
        assert result.diagnosis.top.fault_code.value in text
        assert result.plan.action_type.value in text
        assert result.outcome.value in text
        # The same feature table the diagnoser saw, so a reviewer can line the
        # card up against the diagnosis trace without translating names.
        assert "flow_tail_mean" in text

    def test_a_round_without_a_second_print_renders_without_an_after_score(self) -> None:
        result = _round(FaultCode.CLOG_FULL)
        assert result.after is None
        text = render_round(result)
        assert result.verdict.decision.value in text
        assert " after " not in text


class TestReflector:
    def test_a_round_becomes_a_case_history_card(self) -> None:
        result = _round()
        client = MockLLMClient(scripted=[_draft()])
        card = Reflector(client=client)(result)

        assert card is not None
        assert card.evidence_level is EvidenceLevel.CASE_HISTORY
        assert card.source_url == ""
        assert card.applicable_material == ("PLA",)
        assert card.id.startswith("loop-demo-underext-param-")
        assert client.calls[0].schema_name == "CandidateDraft"

    def test_identity_is_content_addressed(self) -> None:
        """The same round written up in the same words is the same candidate —
        a re-run deduplicates instead of accumulating near-copies."""
        result = _round()
        a = Reflector(client=MockLLMClient(scripted=[_draft()]))(result)
        b = Reflector(client=MockLLMClient(scripted=[_draft()]))(result)
        assert a is not None and b is not None
        assert a.id == b.id

    def test_transport_failure_yields_no_card_and_is_counted(self) -> None:
        reflector = Reflector(client=MockLLMClient(raises=LLMError("outage")))
        assert reflector(_round()) is None
        assert reflector.failures == 1


class TestQuarantine:
    def test_a_candidate_lands_only_in_the_quarantine(self, tmp_path: Path) -> None:
        card = Reflector(client=MockLLMClient(scripted=[_draft()]))(_round())
        assert card is not None

        path = write_candidate(card, root=tmp_path)
        assert path is not None
        assert path.parent.name == CANDIDATE

        # The corpus loader's default — what `printpilot rag build` indexes —
        # must not see the candidate. Round-tripping through the quarantine
        # folder must be lossless, or promotion would alter the card.
        assert load_cards(tmp_path) == []
        assert load_cards(tmp_path, folder=CANDIDATE) == [card]

    def test_a_candidate_is_never_overwritten(self, tmp_path: Path) -> None:
        card = Reflector(client=MockLLMClient(scripted=[_draft()]))(_round())
        assert card is not None

        first = write_candidate(card, root=tmp_path)
        assert first is not None
        before = first.read_text(encoding="utf-8")

        assert write_candidate(card, root=tmp_path) is None
        assert first.read_text(encoding="utf-8") == before

    def test_no_write_path_into_accepted_exists(self) -> None:
        """The structural guarantee itself: the module never references the
        production folder's constant, so no code path in it can write there."""
        source = Path(agent_module.__file__).read_text(encoding="utf-8")
        assert "ACCEPTED" not in source
        assert not hasattr(agent_module, "write_accepted")


class TestCli:
    def test_loop_reflect_refuses_when_unconfigured(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Same guard as the eval arm: inside the suite the LLM is never
        configured, so --reflect must refuse before any round runs."""
        from printpilot.cli import EXIT_NOT_IMPLEMENTED, main

        assert main(["loop", "--reflect"]) == EXIT_NOT_IMPLEMENTED
        captured = capsys.readouterr()
        assert "LLM 未配置" in captured.err
        assert "案例" not in captured.out
