"""Evaluation: metrics, bootstrap intervals, and the split runner."""

from __future__ import annotations

from printpilot.eval.compare import (
    IncomparableRunsError,
    McNemarResult,
    accuracy_by_family,
    compare_runs,
    exact_mcnemar,
    format_comparison,
    top_confusions,
)
from printpilot.eval.metrics import (
    ClassScore,
    EvalReport,
    Interval,
    Prediction,
    format_report,
    score,
)
from printpilot.eval.records import (
    RUNS_ROOT,
    CasePrediction,
    RunRecord,
    build_record,
    load_record,
    save_record,
)
from printpilot.eval.runner import Diagnoser, RunResult, run_split

__all__ = [
    "RUNS_ROOT",
    "CasePrediction",
    "ClassScore",
    "Diagnoser",
    "EvalReport",
    "IncomparableRunsError",
    "Interval",
    "McNemarResult",
    "Prediction",
    "RunRecord",
    "RunResult",
    "accuracy_by_family",
    "build_record",
    "compare_runs",
    "exact_mcnemar",
    "format_comparison",
    "format_report",
    "load_record",
    "run_split",
    "save_record",
    "score",
    "top_confusions",
]
