"""Evaluation runner.

Labels are loaded here and **only** here. The diagnoser is handed a
:class:`PhenomenonReport` built from telemetry alone; nothing that reaches it has
seen ``labels.jsonl``. Scoring happens after every prediction is made.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from printpilot.domain import DiagnosisResult, PhenomenonReport
from printpilot.eval.metrics import EvalReport, Prediction, score
from printpilot.perception import perceive
from printpilot.simulator import Split, load_cases, load_labels

type Diagnoser = Callable[[PhenomenonReport], DiagnosisResult]


def run_split(
    root: Path,
    split: Split,
    diagnoser: Diagnoser,
    *,
    name: str,
) -> EvalReport:
    cases = load_cases(root, split)
    truth = {label.case_id: label.fault_codes[0] for label in load_labels(root, split)}

    predictions: list[Prediction] = []
    for case in cases:
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

    return score(predictions, diagnoser=name, split=split.value)
