"""Retrieval evaluation: Hit@k and MRR against a labelled query set.

A knowledge base with no retrieval evaluation is a demo. The question it answers
is narrow but decisive: when the pipeline asks about a phenomenon, does the card
that addresses it actually come back, and how far down.

MRR is reported alongside Hit@k because they fail differently. Hit@3 says the
right card was somewhere in the window; MRR says whether it was first. A retriever
that reliably places the answer third is worse than the Hit@3 alone suggests,
because everything above it is context the model has to read past.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from printpilot.rag.store import KnowledgeStore

QA_PATH = Path("evals/retrieval_qa.jsonl")
DEFAULT_KS = (1, 3, 5)


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    qid: str
    query: str
    #: Cards that genuinely answer this. More than one is common and expected.
    relevant: tuple[str, ...] = Field(min_length=1)


@dataclass(frozen=True)
class QueryOutcome:
    qid: str
    retrieved: tuple[str, ...]
    relevant: frozenset[str]

    def hit_at(self, k: int) -> bool:
        return bool(set(self.retrieved[:k]) & self.relevant)

    @property
    def reciprocal_rank(self) -> float:
        for rank, card_id in enumerate(self.retrieved, start=1):
            if card_id in self.relevant:
                return 1.0 / rank
        return 0.0


@dataclass(frozen=True)
class RetrievalReport:
    embedder: str
    semantic: bool
    corpus_size: int
    outcomes: tuple[QueryOutcome, ...]
    ks: tuple[int, ...] = DEFAULT_KS

    @property
    def n(self) -> int:
        return len(self.outcomes)

    def hit_rate(self, k: int) -> float:
        return sum(o.hit_at(k) for o in self.outcomes) / self.n if self.n else 0.0

    @property
    def mrr(self) -> float:
        return sum(o.reciprocal_rank for o in self.outcomes) / self.n if self.n else 0.0

    def misses(self) -> list[QueryOutcome]:
        """Where to look first."""
        return [o for o in self.outcomes if not o.hit_at(max(self.ks))]

    def format(self) -> str:
        lines = [
            f"检索评测   embedder={self.embedder}   语料 {self.corpus_size} 条   n={self.n}",
        ]
        if not self.semantic:
            lines.append("  ⚠ 该 embedder 非语义（仅用于打通链路），指标不可对外引用")
        for k in self.ks:
            lines.append(f"  Hit@{k}              {self.hit_rate(k):.3f}")
        lines.append(f"  MRR                 {self.mrr:.3f}")
        missed = self.misses()
        if missed:
            lines.append(f"  未命中 {len(missed)} 条：")
            lines += [
                f"    {o.qid}  期望 {sorted(o.relevant)}  实得 {list(o.retrieved)}" for o in missed
            ]
        return "\n".join(lines)


def load_queries(path: Path | None = None) -> list[RetrievalQuery]:
    with (path or QA_PATH).open(encoding="utf-8") as handle:
        return [RetrievalQuery.model_validate(json.loads(line)) for line in handle if line.strip()]


def evaluate(
    store: KnowledgeStore,
    queries: list[RetrievalQuery],
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> RetrievalReport:
    depth = max(ks)
    outcomes = tuple(
        QueryOutcome(
            qid=q.qid,
            retrieved=tuple(r.card_id for r in store.query(q.query, top_k=depth)),
            relevant=frozenset(q.relevant),
        )
        for q in queries
    )
    return RetrievalReport(
        embedder=store.embedder.name,
        semantic=store.embedder.semantic,
        corpus_size=store.size,
        outcomes=outcomes,
        ks=ks,
    )
