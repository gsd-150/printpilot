"""Bounded concurrency and run accounting.

The ordering test is the important one. Predictions are matched to cases by
position downstream, so results arriving out of order would score every case
against the wrong label — silently, and in a way that looks like a model problem.
"""

from __future__ import annotations

import threading
import time

import pytest

from printpilot.harness import (
    DEFAULT_WORKERS,
    MAX_WORKERS,
    RunCost,
    collect_cost,
    format_cost,
    map_bounded,
    resolve_workers,
)


class TestWorkerResolution:
    def test_default(self) -> None:
        assert resolve_workers(None) == DEFAULT_WORKERS

    def test_caps_runaway_requests(self) -> None:
        """'No documented rate limit' is not 'no limit'."""
        assert resolve_workers(10_000) == MAX_WORKERS

    def test_rejects_zero_and_negative(self) -> None:
        for bad in (0, -1):
            with pytest.raises(ValueError, match="at least 1"):
                resolve_workers(bad)


class TestOrdering:
    def test_results_follow_input_order_not_completion_order(self) -> None:
        def slow_for_early_items(n: int) -> int:
            # Early items finish last, so any completion-ordered implementation
            # returns a reversed list and fails here.
            time.sleep((10 - n) * 0.01)
            return n

        assert map_bounded(slow_for_early_items, list(range(10)), workers=8) == list(range(10))

    def test_single_worker_path_matches(self) -> None:
        assert map_bounded(lambda n: n * 2, [1, 2, 3], workers=1) == [2, 4, 6]

    def test_empty_input(self) -> None:
        assert map_bounded(lambda n: n, [], workers=4) == []

    def test_none_results_are_preserved(self) -> None:
        """None is a legitimate result; completion must not be inferred from it."""
        assert map_bounded(lambda _: None, [1, 2, 3], workers=2) == [None, None, None]


class TestConcurrency:
    def test_actually_runs_in_parallel(self) -> None:
        started = threading.Barrier(4, timeout=5.0)

        def wait_for_others(_: int) -> bool:
            # Only passes if four calls are in flight at once; a serial
            # implementation deadlocks and the barrier times out.
            started.wait()
            return True

        assert all(map_bounded(wait_for_others, list(range(4)), workers=4))

    def test_respects_the_bound(self) -> None:
        lock = threading.Lock()
        peak = 0
        active = 0

        def track(_: int) -> None:
            nonlocal peak, active
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1

        map_bounded(track, list(range(20)), workers=3)
        assert peak <= 3

    def test_progress_is_reported_once_per_item(self) -> None:
        seen: list[int] = []
        lock = threading.Lock()

        def record(done: int, total: int) -> None:
            with lock:
                seen.append(done)

        map_bounded(lambda n: n, list(range(12)), workers=4, progress=record)
        assert sorted(seen) == list(range(1, 13))

    def test_exceptions_propagate(self) -> None:
        """A genuine bug should stop the run, not be averaged into the metrics."""

        def explode(n: int) -> int:
            if n == 5:
                msg = "boom"
                raise RuntimeError(msg)
            return n

        with pytest.raises(RuntimeError, match="boom"):
            map_bounded(explode, list(range(10)), workers=4)


class _FakeUsage:
    prompt_tokens = 1200
    completion_tokens = 800
    latency_ms = 40_000.0


class _FakeClient:
    usage = _FakeUsage()
    call_count = 21
    schema_violations = 3
    repair_attempts = 3


class _FakeDiagnoser:
    client = _FakeClient()
    failures = 1


class TestCostAccounting:
    def test_collects_from_a_client(self) -> None:
        cost = collect_cost(_FakeDiagnoser(), wall_seconds=10.0)
        assert cost.calls == 21
        assert cost.total_tokens == 2000
        assert cost.transport_failures == 1

    def test_speedup_is_measured_not_assumed(self) -> None:
        cost = collect_cost(_FakeDiagnoser(), wall_seconds=10.0)
        assert cost.speedup == pytest.approx(4.0)

    def test_violation_rate(self) -> None:
        assert collect_cost(_FakeDiagnoser(), 10.0).violation_rate == pytest.approx(3 / 21)

    def test_a_diagnoser_without_a_client_is_free(self) -> None:
        """The rules baseline carries no accounting, which is accurate."""
        cost = collect_cost(object(), wall_seconds=1.5)
        assert cost.calls == 0
        assert "无 API 调用" in format_cost(cost, n=100)

    def test_format_reports_tokens_per_case(self) -> None:
        text = format_cost(collect_cost(_FakeDiagnoser(), 10.0), n=20)
        assert "每案例 100" in text
        assert "加速比 4.0×" in text

    def test_zero_cases_does_not_divide_by_zero(self) -> None:
        assert RunCost().per_case(0) == 0.0
