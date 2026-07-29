"""Evaluation metrics.

Top-1 accuracy on its own was rejected in the plan review (P1-1) and would be
misleading here for two reasons:

* the classes carry different **costs** — mistaking a clog for a parameter problem
  means increasing flow into a restricted nozzle, while the reverse merely wastes a
  stop, so a single accuracy number averages over an asymmetry that matters;
* a system allowed to answer ``UNKNOWN`` can buy accuracy by abstaining, so
  abstention has to be reported next to it rather than folded into it.

Confidence intervals are bootstrap percentile intervals. With 30 cases in holdout,
a bare point estimate is not something to quote.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from printpilot.domain import FaultCode, remediation_for

BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE_LEVEL = 0.95

#: Predicting one of these for a case that is actually a clog is the failure mode
#: the safety design exists to prevent: it routes a mechanical fault onto the
#: parameter path.
PARAM_PATH_FAULTS: frozenset[FaultCode] = frozenset(
    {FaultCode.UNDEREXT_PARAM, FaultCode.THERMAL_DRIFT, FaultCode.NORMAL_SUSPICIOUS}
)
CLOG_FAULTS: frozenset[FaultCode] = frozenset({FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL})


@dataclass(frozen=True)
class Prediction:
    case_id: str
    predicted: FaultCode
    truth: FaultCode
    confidence: float

    @property
    def abstained(self) -> bool:
        return self.predicted is FaultCode.UNKNOWN

    @property
    def correct(self) -> bool:
        return self.predicted is self.truth

    @property
    def misroutes_a_clog(self) -> bool:
        """A clog predicted as something the parameter path would accept."""
        return self.truth in CLOG_FAULTS and self.predicted in PARAM_PATH_FAULTS

    @property
    def remediation_correct(self) -> bool:
        if self.abstained:
            return False
        return remediation_for(self.predicted) is remediation_for(self.truth)


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    point: float
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.point:.3f} [{self.low:.3f}, {self.high:.3f}]"


class ClassScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fault: FaultCode
    support: int
    precision: float
    recall: float
    f1: float


class EvalReport(BaseModel):
    """Everything needed to judge one configuration on one split."""

    model_config = ConfigDict(extra="forbid")

    diagnoser: str
    split: str
    n: int = Field(gt=0)
    accuracy: Interval
    macro_f1: float
    #: Fraction of cases answered ``UNKNOWN``. Reported beside accuracy because a
    #: system can trade one for the other.
    abstention_rate: float
    #: Accuracy over the cases where an answer was actually given.
    accuracy_when_answered: float
    #: Whether the *response class* was right, which is what reaches the printer.
    remediation_accuracy: Interval
    #: The safety-critical count: clogs sent down the parameter path. Target zero.
    clog_misroute_rate: Interval
    per_class: list[ClassScore]
    degraded_count: int = 0


def _bootstrap(values: Sequence[float], seed: int = 12345) -> Interval:
    """Percentile interval over the mean of ``values``."""
    if not values:
        return Interval(point=0.0, low=0.0, high=0.0)
    point = sum(values) / len(values)
    if len(values) == 1:
        return Interval(point=point, low=point, high=point)

    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES)
    )
    tail = (1.0 - CONFIDENCE_LEVEL) / 2.0
    low = means[int(tail * BOOTSTRAP_RESAMPLES)]
    high = means[min(BOOTSTRAP_RESAMPLES - 1, int((1.0 - tail) * BOOTSTRAP_RESAMPLES))]
    return Interval(point=point, low=low, high=high)


def _per_class(predictions: Sequence[Prediction]) -> list[ClassScore]:
    scores: list[ClassScore] = []
    observed = sorted({p.truth for p in predictions} | {p.predicted for p in predictions})
    for fault in observed:
        tp = sum(1 for p in predictions if p.predicted is fault and p.truth is fault)
        fp = sum(1 for p in predictions if p.predicted is fault and p.truth is not fault)
        fn = sum(1 for p in predictions if p.truth is fault and p.predicted is not fault)
        support = tp + fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(
            ClassScore(fault=fault, support=support, precision=precision, recall=recall, f1=f1)
        )
    return scores


def score(
    predictions: Sequence[Prediction],
    *,
    diagnoser: str,
    split: str,
    degraded_count: int = 0,
) -> EvalReport:
    per_class = _per_class(predictions)
    # Macro-F1 over the classes that actually occur in the split; UNKNOWN is not a
    # class to be right about, it is a decision to not answer.
    graded = [c for c in per_class if c.support > 0 and c.fault is not FaultCode.UNKNOWN]
    macro_f1 = sum(c.f1 for c in graded) / len(graded) if graded else 0.0

    answered = [p for p in predictions if not p.abstained]
    return EvalReport(
        diagnoser=diagnoser,
        split=split,
        n=len(predictions),
        accuracy=_bootstrap([float(p.correct) for p in predictions]),
        macro_f1=macro_f1,
        abstention_rate=sum(1 for p in predictions if p.abstained) / len(predictions),
        accuracy_when_answered=(
            sum(1 for p in answered if p.correct) / len(answered) if answered else 0.0
        ),
        remediation_accuracy=_bootstrap([float(p.remediation_correct) for p in predictions]),
        clog_misroute_rate=_bootstrap([float(p.misroutes_a_clog) for p in predictions]),
        per_class=per_class,
        degraded_count=degraded_count,
    )


def format_report(report: EvalReport) -> str:
    lines = [
        f"配置 {report.diagnoser}   划分 {report.split}   n={report.n}",
        f"  准确率              {report.accuracy}",
        f"  macro-F1            {report.macro_f1:.3f}",
        f"  弃权率              {report.abstention_rate:.3f}",
        f"  作答时准确率        {report.accuracy_when_answered:.3f}",
        f"  处置类别准确率      {report.remediation_accuracy}",
        f"  堵塞误入参数路径    {report.clog_misroute_rate}   ← 目标 0",
    ]
    if report.degraded_count:
        lines.append(f"  降级次数            {report.degraded_count}")
    lines.append(f"  {'类别':<20}{'支持':>5}{'精确':>9}{'召回':>9}{'F1':>9}")
    for cls in report.per_class:
        lines.append(
            f"  {cls.fault.value:<20}{cls.support:>5}{cls.precision:>9.3f}"
            f"{cls.recall:>9.3f}{cls.f1:>9.3f}"
        )
    return "\n".join(lines)
