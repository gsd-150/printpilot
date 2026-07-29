"""Evaluation runner.

Labels are loaded here and **only** here. The diagnoser is handed a
:class:`PhenomenonReport` built from telemetry alone; nothing that reaches it has
seen ``labels.jsonl``. Scoring happens after every prediction is made.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from printpilot.domain import DiagnosisResult, PhenomenonReport
from printpilot.eval.metrics import EvalReport, Prediction, score
from printpilot.harness import RunCost, collect_cost, map_bounded
from printpilot.perception import perceive
from printpilot.simulator import CaseInput, Split, load_cases, load_labels

type Diagnoser = Callable[[PhenomenonReport], DiagnosisResult]

_progress_lock = threading.Lock()


@dataclass(frozen=True)
class RunResult:
    """Summary, cost, and the individual predictions.

    The predictions were previously discarded once scored, which made paired
    comparison and error attribution impossible after the fact — the two things
    most worth doing with an ablation.
    """

    report: EvalReport
    cost: RunCost
    predictions: list[Prediction]


def stderr_progress(done: int, total: int) -> None:
    """Twenty-second calls need a heartbeat, and it belongs on stderr so piping
    the report to a file still works. Locked because workers report concurrently."""
    with _progress_lock:
        print(f"\r  {done}/{total}", end="", file=sys.stderr, flush=True)
        if done == total:
            print(file=sys.stderr)


def subsample[T](items: list[T], limit: int | None) -> list[T]:
    """Evenly spaced, **not** the first N.

    Cases are written one family at a time, so a prefix of the dev split is
    entirely one fault class — a sample that would validate nothing. Spacing draws
    across families instead. Selection uses position only; labels are never
    consulted to choose cases.
    """
    if limit is None or limit >= len(items):
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def run_split(
    root: Path,
    split: Split,
    diagnoser: Diagnoser,
    *,
    name: str,
    limit: int | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> RunResult:
    """Score one configuration on one split.

    ``limit`` subsamples for prompt iteration. Results from a subsampled run are
    not comparable with a full one, and the split label records it, so a partial
    number cannot later be mistaken for the real thing.
    """
    cases = subsample(load_cases(root, split), limit)
    truth = {label.case_id: label.fault_codes[0] for label in load_labels(root, split)}

    def evaluate(case: CaseInput) -> Prediction:
        # Only telemetry and material cross into perception. Not family_id, not
        # split, not anything derived from the label file.
        report = perceive(case.telemetry, material=case.material.value)
        result = diagnoser(report)
        return Prediction(
            case_id=case.case_id,
            predicted=result.top.fault_code,
            truth=truth[case.case_id],
            confidence=result.top.confidence,
            family_id=case.family_id,
            skills_used=tuple(result.skills_used),
            retrieved_chunk_ids=tuple(result.retrieved_chunk_ids),
        )

    started = time.perf_counter()
    predictions = map_bounded(evaluate, cases, workers=workers, progress=progress)
    elapsed = time.perf_counter() - started

    label = split.value if limit is None else f"{split.value}[:{limit}]"
    return RunResult(
        report=score(predictions, diagnoser=name, split=label),
        cost=collect_cost(diagnoser, elapsed),
        predictions=predictions,
    )
