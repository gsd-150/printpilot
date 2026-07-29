"""Paired comparison and error attribution.

Two configurations that ran over the same cases should be compared *pairwise*.
Independent confidence intervals discard the pairing: they ask whether two
populations differ, when the question is whether one configuration beats the other
on the cases where they disagreed. Overlapping intervals are routinely compatible
with a decisive paired result.

McNemar's test uses exactly the discordant cases. The exact binomial form is used
rather than the chi-square approximation because these runs are small — a hundred
cases with a handful of disagreements is where the approximation is least
trustworthy, and ``math.comb`` makes the exact version free.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import comb

from printpilot.domain import FaultCode
from printpilot.eval.records import RunRecord


class IncomparableRunsError(ValueError):
    """The two runs do not answer the same question."""


@dataclass(frozen=True)
class McNemarResult:
    """``only_a`` and ``only_b`` are the discordant counts — the whole test."""

    both_correct: int
    only_a: int
    only_b: int
    both_wrong: int
    p_value: float

    @property
    def n(self) -> int:
        return self.both_correct + self.only_a + self.only_b + self.both_wrong

    @property
    def discordant(self) -> int:
        return self.only_a + self.only_b

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05

    def verdict(self, name_a: str, name_b: str) -> str:
        if self.discordant == 0:
            return "两次运行逐案例完全一致，无可比较的差异。"
        better, worse = (name_b, name_a) if self.only_b > self.only_a else (name_a, name_b)
        direction = f"{better} 优于 {worse}"
        if self.significant:
            return f"{direction}（p={self.p_value:.4f}，配对显著）"
        return (
            f"{direction}，但 p={self.p_value:.4f} 未达显著；"
            f"分歧样本仅 {self.discordant} 条，不足以下结论。"
        )


def exact_mcnemar(only_a: int, only_b: int) -> float:
    """Two-sided exact binomial p-value over the discordant pairs.

    Under the null the two configurations are equally likely to win any case they
    disagree on, so the discordant counts are Binomial(n, 0.5).
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2**n)
    return float(min(1.0, 2.0 * tail))


def compare_runs(a: RunRecord, b: RunRecord) -> McNemarResult:
    """Pair two runs case by case.

    Refuses runs that are not answering the same question. A comparison across
    different splits or different models silently measures the wrong thing, and
    the cost of that mistake is a confident conclusion about nothing.
    """
    if a.split != b.split:
        msg = f"different splits: {a.split!r} vs {b.split!r}"
        raise IncomparableRunsError(msg)
    if a.model and b.model and a.model != b.model:
        msg = (
            f"different models: {a.model!r} vs {b.model!r} — "
            "this would compare models, not configurations"
        )
        raise IncomparableRunsError(msg)

    left, right = a.by_case(), b.by_case()
    shared = sorted(set(left) & set(right))
    if not shared:
        msg = "the two runs share no case ids"
        raise IncomparableRunsError(msg)

    both_correct = only_a = only_b = both_wrong = 0
    for case_id in shared:
        ca, cb = left[case_id].correct, right[case_id].correct
        if ca and cb:
            both_correct += 1
        elif ca:
            only_a += 1
        elif cb:
            only_b += 1
        else:
            both_wrong += 1

    return McNemarResult(
        both_correct=both_correct,
        only_a=only_a,
        only_b=only_b,
        both_wrong=both_wrong,
        p_value=exact_mcnemar(only_a, only_b),
    )


def confusion(record: RunRecord) -> dict[tuple[FaultCode, FaultCode], int]:
    """``(truth, predicted) -> count``."""
    return dict(Counter((p.truth, p.predicted) for p in record.predictions))


def top_confusions(record: RunRecord, limit: int = 5) -> list[tuple[FaultCode, FaultCode, int]]:
    """The most frequent mistakes, largest first. Where to look first."""
    wrong = [
        (truth, predicted, count)
        for (truth, predicted), count in confusion(record).items()
        if truth is not predicted
    ]
    wrong.sort(key=lambda row: (-row[2], row[0].value, row[1].value))
    return wrong[:limit]


def accuracy_by_family(record: RunRecord) -> dict[str, tuple[int, int]]:
    """``family_id -> (correct, total)``.

    Family is the unit the dataset was split on, so it is also the unit at which a
    weakness is worth acting on: a failure concentrated in one family points at
    that generating structure, not at the model in general.
    """
    totals: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    for prediction in record.predictions:
        totals[prediction.family_id] += 1
        if prediction.correct:
            hits[prediction.family_id] += 1
    return {family: (hits[family], totals[family]) for family in sorted(totals)}


def format_comparison(a: RunRecord, b: RunRecord) -> str:
    result = compare_runs(a, b)
    lines = [
        f"配对比较   {a.name}  vs  {b.name}",
        f"  划分 {a.split}   模型 {a.model or '(未记录)'}   n={result.n}",
        "",
        f"  两者皆对        {result.both_correct}",
        f"  仅 {a.name} 对   {result.only_a}",
        f"  仅 {b.name} 对   {result.only_b}",
        f"  两者皆错        {result.both_wrong}",
        "",
        f"  准确率          {a.accuracy:.3f} → {b.accuracy:.3f}",
        f"  McNemar 精确检验 p={result.p_value:.4f}",
        f"  结论：{result.verdict(a.name, b.name)}",
    ]

    for record in (a, b):
        mistakes = top_confusions(record)
        if mistakes:
            lines.append(f"\n  {record.name} 的主要混淆：")
            lines += [
                f"    {truth.value:<20} 判为 {predicted.value:<20} {count} 次"
                for truth, predicted, count in mistakes
            ]
    return "\n".join(lines)
