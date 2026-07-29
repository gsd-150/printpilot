"""Paired comparison and error attribution.

The reason this exists: three configurations ran over the same cases, and comparing
them with independent confidence intervals throws the pairing away. Two intervals
can overlap comfortably while every single disagreement points one way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printpilot.domain import FaultCode
from printpilot.eval import (
    CasePrediction,
    IncomparableRunsError,
    RunRecord,
    accuracy_by_family,
    compare_runs,
    exact_mcnemar,
    format_comparison,
    load_record,
    save_record,
    top_confusions,
)


def _record(
    name: str,
    outcomes: list[tuple[FaultCode, FaultCode]],
    *,
    split: str = "dev",
    model: str = "m1",
) -> RunRecord:
    return RunRecord(
        name=name,
        diagnoser=name,
        split=split,
        model=model,
        predictions=[
            CasePrediction(
                case_id=f"dev-{i:04d}",
                family_id=f"{truth.value}/PLA/box/nominal",
                predicted=predicted,
                truth=truth,
                confidence=0.8,
            )
            for i, (truth, predicted) in enumerate(outcomes)
        ],
    )


CLOG = FaultCode.CLOG_PARTIAL
FULL = FaultCode.CLOG_FULL
PARAM = FaultCode.UNDEREXT_PARAM


class TestExactMcNemar:
    def test_no_disagreement_is_no_evidence(self) -> None:
        assert exact_mcnemar(0, 0) == 1.0

    def test_a_lopsided_split_is_significant(self) -> None:
        """Twelve disagreements all favouring one side."""
        assert exact_mcnemar(0, 12) < 0.001

    def test_an_even_split_is_not(self) -> None:
        assert exact_mcnemar(6, 6) == pytest.approx(1.0)

    def test_a_small_lopsided_split_is_not_significant(self) -> None:
        """Three-nil looks decisive and is not: p = 0.25."""
        assert exact_mcnemar(0, 3) == pytest.approx(0.25)

    def test_is_symmetric(self) -> None:
        assert exact_mcnemar(2, 9) == exact_mcnemar(9, 2)

    def test_never_exceeds_one(self) -> None:
        for a in range(6):
            for b in range(6):
                assert 0.0 <= exact_mcnemar(a, b) <= 1.0


class TestPairing:
    def test_counts_the_four_cells(self) -> None:
        a = _record("a", [(CLOG, CLOG), (CLOG, CLOG), (CLOG, PARAM), (CLOG, PARAM)])
        b = _record("b", [(CLOG, CLOG), (CLOG, PARAM), (CLOG, CLOG), (CLOG, PARAM)])
        result = compare_runs(a, b)
        assert (result.both_correct, result.only_a, result.only_b, result.both_wrong) == (
            1,
            1,
            1,
            1,
        )

    def test_detects_a_consistent_improvement_that_intervals_would_miss(self) -> None:
        """Ten cases both get right, six that only B gets right, none the other way.
        Independent intervals on 0.625 vs 1.0 at n=16 would be far less decisive."""
        shared = [(CLOG, CLOG)] * 10
        a = _record("a", shared + [(PARAM, CLOG)] * 6)
        b = _record("b", shared + [(PARAM, PARAM)] * 6)
        result = compare_runs(a, b)
        assert result.only_b == 6
        assert result.only_a == 0
        assert result.significant

    def test_verdict_names_the_winner(self) -> None:
        a = _record("a", [(PARAM, CLOG)] * 8)
        b = _record("b", [(PARAM, PARAM)] * 8)
        assert "b 优于 a" in compare_runs(a, b).verdict("a", "b")

    def test_verdict_admits_when_the_sample_is_too_small(self) -> None:
        a = _record("a", [(PARAM, CLOG)] * 2)
        b = _record("b", [(PARAM, PARAM)] * 2)
        verdict = compare_runs(a, b).verdict("a", "b")
        assert "未达显著" in verdict

    def test_identical_runs_report_no_difference(self) -> None:
        a = _record("a", [(CLOG, CLOG), (PARAM, PARAM)])
        b = _record("b", [(CLOG, CLOG), (PARAM, PARAM)])
        assert "完全一致" in compare_runs(a, b).verdict("a", "b")


class TestRefusals:
    def test_different_splits(self) -> None:
        with pytest.raises(IncomparableRunsError, match="different splits"):
            compare_runs(
                _record("a", [(CLOG, CLOG)]), _record("b", [(CLOG, CLOG)], split="holdout")
            )

    def test_different_models(self) -> None:
        """Comparing across models measures the model, not the configuration."""
        with pytest.raises(IncomparableRunsError, match="compare models"):
            compare_runs(_record("a", [(CLOG, CLOG)]), _record("b", [(CLOG, CLOG)], model="m2"))

    def test_a_run_with_no_model_compares_against_any(self) -> None:
        """The rules arm records no model. Blocking it would rule out the
        rules-vs-LLM comparison the ablation is built around."""
        rules = _record("rules", [(CLOG, CLOG)], model="")
        llm = _record("llm", [(CLOG, PARAM)], model="claude-sonnet-4-5")
        assert compare_runs(rules, llm).only_a == 1

    def test_no_shared_cases(self) -> None:
        a = _record("a", [(CLOG, CLOG)])
        b = _record("b", [(CLOG, CLOG)])
        b = b.model_copy(
            update={"predictions": [b.predictions[0].model_copy(update={"case_id": "dev-9999"})]}
        )
        with pytest.raises(IncomparableRunsError, match="share no case ids"):
            compare_runs(a, b)


class TestAttribution:
    def test_top_confusions_ranks_the_biggest_mistake_first(self) -> None:
        record = _record("a", [(FULL, CLOG)] * 5 + [(PARAM, CLOG)] * 2 + [(CLOG, CLOG)] * 3)
        top = top_confusions(record)
        assert top[0] == (FULL, CLOG, 5)
        assert all(truth is not predicted for truth, predicted, _ in top)

    def test_accuracy_by_family_localises_a_weakness(self) -> None:
        """Family is the unit the dataset was split on, so a failure concentrated
        there points at a generating structure rather than at the model at large."""
        record = _record("a", [(FULL, CLOG)] * 4 + [(PARAM, PARAM)] * 4)
        by_family = accuracy_by_family(record)
        assert by_family["CLOG_FULL/PLA/box/nominal"] == (0, 4)
        assert by_family["UNDEREXT_PARAM/PLA/box/nominal"] == (4, 4)


class TestPersistence:
    def test_round_trip(self, tmp_path: Path) -> None:
        record = _record("a", [(CLOG, CLOG), (PARAM, CLOG)])
        loaded = load_record(save_record(record, tmp_path))
        assert loaded.name == "a"
        assert loaded.accuracy == pytest.approx(0.5)
        assert [p.case_id for p in loaded.predictions] == ["dev-0000", "dev-0001"]

    def test_format_comparison_reports_the_p_value(self) -> None:
        a = _record("a", [(PARAM, CLOG)] * 8)
        b = _record("b", [(PARAM, PARAM)] * 8)
        text = format_comparison(a, b)
        assert "McNemar" in text
        assert "主要混淆" in text
