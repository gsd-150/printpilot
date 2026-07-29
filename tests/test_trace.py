"""Tracing.

What "I can find out why it did that" has to survive: a failing step must still
appear, concurrent workers must not corrupt the record, and a case must be
reconstructable from the file alone.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from printpilot.harness import DISABLED, Step, Tracer


class TestRecording:
    def test_records_a_step(self) -> None:
        tracer = Tracer()
        tracer.record("c1", Step.DIAGNOSIS, predicted="CLOG_PARTIAL")
        assert len(tracer.events) == 1
        assert tracer.events[0].detail["predicted"] == "CLOG_PARTIAL"

    def test_span_times_the_body(self) -> None:
        tracer = Tracer()
        with tracer.span("c1", Step.RETRIEVAL):
            pass
        assert tracer.events[0].duration_ms >= 0.0

    def test_span_body_can_add_what_it_produced(self) -> None:
        """A step should report its output, not only its input."""
        tracer = Tracer()
        with tracer.span("c1", Step.RETRIEVAL, top_k=2) as span:
            span["chunks"] = ["a", "b"]
        detail = tracer.events[0].detail
        assert detail["top_k"] == 2
        assert detail["chunks"] == ["a", "b"]

    def test_a_failing_step_is_still_recorded(self) -> None:
        """The step that vanishes when it errors is the one you needed to see."""
        tracer = Tracer()
        with pytest.raises(ValueError, match="boom"), tracer.span("c1", Step.DIAGNOSIS):
            msg = "boom"
            raise ValueError(msg)
        assert tracer.events[0].error.startswith("ValueError")

    def test_the_exception_still_propagates(self) -> None:
        tracer = Tracer()
        with pytest.raises(RuntimeError), tracer.span("c1", Step.SAFETY):
            raise RuntimeError

    def test_disabled_tracer_records_nothing(self) -> None:
        DISABLED.record("c1", Step.DIAGNOSIS)
        with DISABLED.span("c1", Step.SAFETY):
            pass
        assert DISABLED.events == []


class TestConcurrency:
    def test_events_from_many_workers_are_all_kept(self) -> None:
        tracer = Tracer()

        def worker(index: int) -> None:
            for _ in range(20):
                tracer.record(f"c{index}", Step.DIAGNOSIS)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(tracer.events) == 160


class TestOutput:
    def test_written_file_is_one_json_object_per_line(self, tmp_path: Path) -> None:
        tracer = Tracer()
        tracer.record("c1", Step.DIAGNOSIS, predicted="CLOG_FULL")
        tracer.record("c2", Step.SAFETY, decision="block")
        lines = tracer.write(tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["case_id"] for line in lines] == ["c1", "c2"]

    def test_events_are_grouped_by_case(self, tmp_path: Path) -> None:
        """Workers interleave, and an interleaved trace is unreadable exactly when
        it is needed."""
        tracer = Tracer()
        for case in ("c2", "c1", "c2", "c1"):
            tracer.record(case, Step.DIAGNOSIS)
        lines = tracer.write(tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        cases = [json.loads(line)["case_id"] for line in lines]
        assert cases == sorted(cases)

    def test_non_serialisable_detail_does_not_break_the_write(self, tmp_path: Path) -> None:
        tracer = Tracer()
        tracer.record("c1", Step.DECISION, plan=object())
        assert tracer.write(tmp_path / "t.jsonl").exists()

    def test_replay_reconstructs_one_case(self) -> None:
        tracer = Tracer()
        tracer.record("c1", Step.RETRIEVAL, chunks=["a"])
        tracer.record("c1", Step.DIAGNOSIS, predicted="CLOG_PARTIAL")
        tracer.record("c2", Step.DIAGNOSIS, predicted="UNKNOWN")
        text = tracer.replay("c1")
        assert "retrieval" in text
        assert "CLOG_PARTIAL" in text
        assert "UNKNOWN" not in text

    def test_replay_of_an_unknown_case_says_so(self) -> None:
        assert "无 trace 记录" in Tracer().replay("nope")

    def test_for_case_filters(self) -> None:
        tracer = Tracer()
        tracer.record("c1", Step.DIAGNOSIS)
        tracer.record("c2", Step.DIAGNOSIS)
        assert len(tracer.for_case("c1")) == 1
