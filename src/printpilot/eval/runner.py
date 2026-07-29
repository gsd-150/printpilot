"""Evaluation runner.

Labels are loaded here and **only** here. The diagnoser is handed a
:class:`PhenomenonReport` built from telemetry alone; nothing that reaches it has
seen ``labels.jsonl``. Scoring happens after every prediction is made.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from printpilot.domain import DiagnosisResult, PhenomenonReport
from printpilot.eval.metrics import EvalReport, Prediction, score
from printpilot.perception import perceive
from printpilot.simulator import Split, load_cases, load_labels

type Diagnoser = Callable[[PhenomenonReport], DiagnosisResult]


def stderr_progress(done: int, total: int) -> None:
    """Twenty-second calls need a heartbeat, and it belongs on stderr so piping
    the report to a file still works."""
    print(f"\r  {done}/{total}", end="", file=sys.stderr, flush=True)
    if done == total:
        print(file=sys.stderr)


def run_split(
    root: Path,
    split: Split,
    diagnoser: Diagnoser,
    *,
    name: str,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> EvalReport:
    """Score one configuration on one split.

    ``limit`` subsamples the split for prompt iteration. Results from a subsampled
    run are not comparable with a full one and the split label records it, so a
    partial number cannot later be mistaken for the real thing.

    The subsample is **evenly spaced, not the first N**. Cases are written one
    family at a time, so a prefix of the dev split is entirely one fault class —
    a sample that would validate nothing. Spacing draws across families instead.
    Selection uses position only; labels are not consulted to choose cases.
    """
    cases = load_cases(root, split)
    truth = {label.case_id: label.fault_codes[0] for label in load_labels(root, split)}
    if limit is not None and limit < len(cases):
        step = len(cases) / limit
        cases = [cases[int(i * step)] for i in range(limit)]

    predictions: list[Prediction] = []
    for index, case in enumerate(cases, start=1):
        # Only telemetry and material cross into perception. Not family_id, not
        # split, not anything derived from the label file.
        report = perceive(case.telemetry, material=case.material.value)
        result = diagnoser(report)
        predictions.append(
            Prediction(
                case_id=case.case_id,
                predicted=result.top.fault_code,
                truth=truth[case.case_id],
                confidence=result.top.confidence,
            )
        )
        if progress is not None:
            progress(index, len(cases))

    label = split.value if limit is None else f"{split.value}[:{limit}]"
    return score(predictions, diagnoser=name, split=label)
