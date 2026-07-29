"""Corpus cleaning, with before/after counts.

A cleaning step that reports nothing has not been shown to do anything. Each rule
returns what it dropped and why, so the pipeline can state "12 cards in, 12 out,
0 duplicates, 0 too short" rather than asserting the corpus is clean.

The rules are ordered cheapest-first, and each is independent — a card rejected by
one is not passed to the next, so the counts partition rather than overlap.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from printpilot.rag.cards import KnowledgeCard

#: Shorter than this and there is no claim, only a heading.
MIN_BODY_CHARS = 80

#: Jaccard similarity over character trigrams above which two cards are the same
#: card. Trigrams rather than words because the corpus is Chinese and unsegmented.
DUPLICATE_THRESHOLD = 0.80


@dataclass
class CleaningReport:
    total_in: int = 0
    kept: list[KnowledgeCard] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_out(self) -> int:
        return len(self.kept)

    def reasons(self) -> dict[str, int]:
        return dict(Counter(reason for _, reason in self.dropped))

    def format(self) -> str:
        lines = [f"语料清洗：{self.total_in} 进 → {self.total_out} 出"]
        if not self.dropped:
            lines.append("  未剔除任何卡片")
        for reason, count in sorted(self.reasons().items()):
            lines.append(f"  剔除 {count} 条：{reason}")
        for card_id, reason in self.dropped:
            lines.append(f"    - {card_id}（{reason}）")
        return "\n".join(lines)


def _trigrams(text: str) -> set[str]:
    stripped = "".join(text.split())
    return {stripped[i : i + 3] for i in range(max(0, len(stripped) - 2))}


def similarity(a: str, b: str) -> float:
    left, right = _trigrams(a), _trigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def clean(cards: list[KnowledgeCard]) -> CleaningReport:
    report = CleaningReport(total_in=len(cards))
    seen_ids: set[str] = set()
    superseded = {c.supersedes for c in cards if c.supersedes}

    for card in cards:
        if card.id in seen_ids:
            report.dropped.append((card.id, "id 重复"))
            continue
        if len(card.body) < MIN_BODY_CHARS:
            report.dropped.append((card.id, f"正文不足 {MIN_BODY_CHARS} 字"))
            continue
        if card.id in superseded:
            report.dropped.append((card.id, "已被更新版本取代"))
            continue

        duplicate = next(
            (
                kept.id
                for kept in report.kept
                if similarity(kept.body, card.body) > DUPLICATE_THRESHOLD
            ),
            None,
        )
        if duplicate:
            report.dropped.append((card.id, f"与 {duplicate} 近重复"))
            continue

        seen_ids.add(card.id)
        report.kept.append(card)

    return report
