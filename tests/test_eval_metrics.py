"""Metrics.

The design question these encode: an accuracy number alone cannot tell "wrong"
apart from "declined to answer", and cannot tell a harmless confusion apart from
one that would push flow into a clogged nozzle. So it is never reported alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printpilot.diagnosis import diagnose
from printpilot.domain import FaultCode
from printpilot.eval import Prediction, format_report, run_split, score
from printpilot.simulator import Split, write_dataset


def _p(predicted: FaultCode, truth: FaultCode, confidence: float = 0.8) -> Prediction:
    return Prediction(case_id="c", predicted=predicted, truth=truth, confidence=confidence)


class TestPredictionSemantics:
    def test_abstention_is_not_counted_as_correct(self) -> None:
        p = _p(FaultCode.UNKNOWN, FaultCode.CLOG_PARTIAL)
        assert p.abstained
        assert not p.correct

    def test_clog_misroute_detects_the_dangerous_confusion(self) -> None:
        assert _p(FaultCode.UNDEREXT_PARAM, FaultCode.CLOG_PARTIAL).misroutes_a_clog

    def test_abstaining_on_a_clog_is_not_a_misroute(self) -> None:
        """Refusing to answer is cautious, not dangerous — it reaches no action."""
        assert not _p(FaultCode.UNKNOWN, FaultCode.CLOG_PARTIAL).misroutes_a_clog

    def test_confusing_two_clogs_is_not_a_misroute(self) -> None:
        assert not _p(FaultCode.CLOG_FULL, FaultCode.CLOG_PARTIAL).misroutes_a_clog

    def test_remediation_can_be_right_while_the_fault_is_wrong(self) -> None:
        """Thermal drift and parameter under-extrusion are both param-fixable, so
        confusing them changes nothing the printer does."""
        p = _p(FaultCode.UNDEREXT_PARAM, FaultCode.THERMAL_DRIFT)
        assert not p.correct
        assert p.remediation_correct


class TestScoring:
    def test_perfect_predictions(self) -> None:
        report = score(
            [_p(f, f) for f in (FaultCode.CLOG_FULL, FaultCode.UNDEREXT_PARAM)] * 5,
            diagnoser="t",
            split="dev",
        )
        assert report.accuracy.point == pytest.approx(1.0)
        assert report.macro_f1 == pytest.approx(1.0)
        assert report.abstention_rate == pytest.approx(0.0)

    def test_abstention_lowers_accuracy_but_not_answered_accuracy(self) -> None:
        predictions = [_p(FaultCode.CLOG_FULL, FaultCode.CLOG_FULL)] * 3 + [
            _p(FaultCode.UNKNOWN, FaultCode.CLOG_PARTIAL)
        ]
        report = score(predictions, diagnoser="t", split="dev")
        assert report.accuracy.point == pytest.approx(0.75)
        assert report.abstention_rate == pytest.approx(0.25)
        assert report.accuracy_when_answered == pytest.approx(1.0)

    def test_unknown_is_excluded_from_macro_f1(self) -> None:
        """UNKNOWN is a decision not to answer, not a class to be scored on."""
        report = score(
            [_p(FaultCode.CLOG_FULL, FaultCode.CLOG_FULL)] * 3
            + [_p(FaultCode.UNKNOWN, FaultCode.CLOG_FULL)],
            diagnoser="t",
            split="dev",
        )
        assert FaultCode.UNKNOWN not in {c.fault for c in report.per_class if c.support}

    def test_interval_brackets_the_point_estimate(self) -> None:
        report = score(
            [_p(FaultCode.CLOG_FULL, FaultCode.CLOG_FULL)] * 7
            + [_p(FaultCode.CLOG_FULL, FaultCode.UNDEREXT_PARAM)] * 3,
            diagnoser="t",
            split="dev",
        )
        assert report.accuracy.low <= report.accuracy.point <= report.accuracy.high
        assert report.accuracy.high > report.accuracy.low, "n=10 cannot give a tight interval"

    def test_intervals_are_deterministic(self) -> None:
        predictions = [_p(FaultCode.CLOG_FULL, FaultCode.CLOG_FULL)] * 6 + [
            _p(FaultCode.CLOG_FULL, FaultCode.UNDEREXT_PARAM)
        ] * 4
        a = score(predictions, diagnoser="t", split="dev")
        b = score(predictions, diagnoser="t", split="dev")
        assert a.accuracy == b.accuracy

    def test_format_includes_the_safety_metric(self) -> None:
        text = format_report(
            score([_p(FaultCode.CLOG_FULL, FaultCode.CLOG_FULL)], diagnoser="t", split="dev")
        )
        assert "堵塞误入参数路径" in text


class TestRunnerIsolation:
    @pytest.fixture(scope="class")
    def root(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        path = tmp_path_factory.mktemp("eval")
        write_dataset(path, master_seed=42)
        return path

    def test_diagnoser_never_receives_a_label(self, root: Path) -> None:
        seen: list[object] = []

        def spy(report: object) -> object:
            seen.append(report)
            return diagnose(report)  # type: ignore[arg-type]

        run_split(root, Split.HOLDOUT, spy, name="spy")  # type: ignore[arg-type]

        assert len(seen) == 30
        for report in seen:
            dumped = str(report)
            for leak in ("CLOG_", "UNDEREXT_", "THERMAL_", "NORMAL_", "remediation"):
                assert leak not in dumped, f"{leak} reached the diagnoser"

    def test_rules_baseline_generalises_to_holdout(self, root: Path) -> None:
        """A guard against a regression that only shows up off the dev split."""
        assert run_split(root, Split.HOLDOUT, diagnose, name="rules").report.accuracy.point > 0.80

    def test_rules_baseline_never_misroutes_a_clog(self, root: Path) -> None:
        for split in Split:
            result = run_split(root, split, diagnose, name="rules")
            assert result.report.clog_misroute_rate.point == 0.0, f"{split} misrouted a clog"

    def test_blinded_challenge_cases_drive_abstention(self, root: Path) -> None:
        """10 of the 30 challenge cases have the discriminating signal removed."""
        result = run_split(root, Split.CHALLENGE, diagnose, name="rules")
        assert result.report.abstention_rate == pytest.approx(10 / 30)

    def test_predictions_are_retained_for_later_analysis(self, root: Path) -> None:
        """Discarding them once scored made paired comparison impossible after the
        fact — the most useful thing to do with an ablation."""
        result = run_split(root, Split.HOLDOUT, diagnose, name="rules")
        assert len(result.predictions) == 30
        assert all(p.family_id for p in result.predictions)

    def test_concurrency_does_not_change_results(self, root: Path) -> None:
        """Each case is an independent call; parallelism must be invisible in the
        scores, or every ablation comparison is confounded by worker count."""
        serial = run_split(root, Split.DEV, diagnose, name="rules", workers=1)
        parallel = run_split(root, Split.DEV, diagnose, name="rules", workers=8)
        assert serial.report.accuracy == parallel.report.accuracy
        assert serial.report.per_class == parallel.report.per_class
        assert serial.predictions == parallel.predictions

    def test_subsample_spreads_across_families(self, root: Path) -> None:
        """A prefix of dev is one fault class; the sample has to reach further."""
        from printpilot.eval.runner import subsample
        from printpilot.simulator import load_cases

        cases = load_cases(root, Split.DEV)
        assert len({c.family_id for c in cases[:20]}) < 5
        assert len({c.family_id for c in subsample(cases, 20)}) == 20
