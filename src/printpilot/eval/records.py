"""Per-case run records.

Summary metrics alone cannot answer the two questions that matter after an
ablation: *is this difference real* and *where exactly did it come from*. Both
need the individual predictions.

The paired point is the sharper one. Three configurations run over the **same**
cases, so comparing them with independent confidence intervals throws away the
pairing and is needlessly conservative — two intervals can overlap while every
single disagreement points the same way. McNemar's test uses only the cases where
the two configurations disagreed, which is where the information actually is.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from printpilot.domain import FaultCode
from printpilot.eval.metrics import EvalReport, Prediction
from printpilot.harness import RunCost

RUNS_ROOT = Path("evals/runs")
RECORD_SCHEMA_VERSION = "1.0.0"


class CasePrediction(BaseModel):
    """One case, one configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    family_id: str
    predicted: FaultCode
    truth: FaultCode
    confidence: float
    skills_used: list[str] = Field(default_factory=list)

    @property
    def correct(self) -> bool:
        return self.predicted is self.truth


class RunRecord(BaseModel):
    """Everything needed to re-read, compare, or attribute a run.

    The provenance fields are not decoration: a comparison between runs made with
    different models or prompts measures something other than what it claims to,
    and :func:`printpilot.eval.compare.compare_runs` refuses such pairs.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = RECORD_SCHEMA_VERSION
    name: str
    diagnoser: str
    split: str
    model: str = ""
    prompt: str = ""
    dataset_seed: int | None = None
    created_at: str = ""
    predictions: list[CasePrediction]
    cost: RunCost = Field(default_factory=RunCost)

    @property
    def accuracy(self) -> float:
        if not self.predictions:
            return 0.0
        return sum(1 for p in self.predictions if p.correct) / len(self.predictions)

    def by_case(self) -> dict[str, CasePrediction]:
        return {p.case_id: p for p in self.predictions}


def build_record(
    *,
    name: str,
    report: EvalReport,
    predictions: list[Prediction],
    cost: RunCost,
    model: str = "",
    prompt: str = "",
    dataset_seed: int | None = None,
) -> RunRecord:
    return RunRecord(
        name=name,
        diagnoser=report.diagnoser,
        split=report.split,
        model=model,
        prompt=prompt,
        dataset_seed=dataset_seed,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        predictions=[
            CasePrediction(
                case_id=p.case_id,
                family_id=p.family_id,
                predicted=p.predicted,
                truth=p.truth,
                confidence=p.confidence,
                skills_used=list(p.skills_used),
            )
            for p in predictions
        ],
        cost=cost,
    )


def save_record(record: RunRecord, root: Path | None = None) -> Path:
    base = root or RUNS_ROOT
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{record.name}.json"
    path.write_text(
        json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_record(path: Path) -> RunRecord:
    return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
