"""Reflection: the round becomes a candidate knowledge card — and only a candidate.

This is the node the v2 design calls ReflectionAgent, and the constraint that
makes it safe to run unattended lives in the file system, not in the prompt:
the card lands in ``knowledge/candidate_cases/``, a quarantine nothing else
reads. ``load_cards()`` defaults to ``accepted/``, so ``printpilot rag build``
cannot index a candidate no matter what the model wrote. Promotion is a human
act — review against the round record, move the file, rebuild the index (see
``knowledge/README.md``). A reflection that fed the next diagnosis unreviewed
would be exactly the loop v2's revision note #6 forbids.

The model is shown the observable round: measured features, the diagnosis, the
plan, the gate's ruling, and quality before and after. It is never shown the
injected fault, for the same reason the quality evaluator is blind to it — a
card carrying the generator's label would leak the answer key into a corpus
the diagnoser may later read.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from printpilot.diagnosis.llm import render_phenomenon
from printpilot.harness.trace import DISABLED, Step, Tracer
from printpilot.llm.base import LLMClient, LLMError
from printpilot.loop import LoopResult
from printpilot.prompts import Prompt, load_prompt
from printpilot.rag.cards import CANDIDATE, KNOWLEDGE_ROOT, EvidenceLevel, KnowledgeCard

DEFAULT_PROMPT = "reflection/v1_baseline"


class CandidateDraft(BaseModel):
    """Everything the model authors — and nothing more.

    Identity, provenance, material and evidence level are filled in by code:
    what the card *says* is the model's claim, where it came from is a fact,
    and facts are recorded rather than requested.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1)
    tags: tuple[str, ...] = ()


def render_round(result: LoopResult) -> str:
    """Lay out the round for the model — the observable record and nothing else.

    Reuses :func:`render_phenomenon` so a reviewer checking a card against a
    trace reads the same feature table the diagnoser saw.
    """
    lines = [
        render_phenomenon(result.report),
        "",
        "Round record:",
        f"  diagnosis   {result.diagnosis.top.fault_code.value}"
        f"  (confidence {result.diagnosis.top.confidence:.2f})",
        f"  action      {result.plan.action_type.value}  (risk {result.plan.risk_level.value})",
        f"  rationale   {result.plan.rationale}",
    ]
    lines += [
        f"    patch     {change.param.value} {change.delta:+g} {change.unit.value}"
        for change in result.plan.patch
    ]
    gate = f"  gate        {result.verdict.decision.value}"
    if result.verdict.violated_rules:
        gate += "  (" + "; ".join(result.verdict.violated_rules) + ")"
    lines.append(gate)
    quality = f"  quality     before {result.before.score:.3f}"
    if result.after is not None:
        quality += f"  after {result.after.score:.3f}  (delta {result.delta:+.3f})"
    lines += [quality, f"  outcome     {result.outcome.value}"]
    return "\n".join(lines)


@dataclass
class Reflector:
    """The loop's writing end. Called once per round, serially — unlike the
    diagnoser it needs no lock, and growing one should wait for a caller that
    actually fans out.

    Returns ``None`` on transport failure: a round that could not be written up
    is a missing card, not a reason to crash a demo that already printed its
    summary — the counter keeps the failure from being silent.
    """

    client: LLMClient
    prompt: Prompt = field(default_factory=lambda: load_prompt(DEFAULT_PROMPT))
    tracer: Tracer = field(default_factory=lambda: DISABLED)
    failures: int = 0

    def __call__(self, result: LoopResult) -> KnowledgeCard | None:
        rendered = self.prompt.render(round=render_round(result))
        try:
            with self.tracer.span(result.case_id, Step.REFLECTION, prompt=self.prompt.name) as span:
                draft = self.client.complete_structured(prompt=rendered, schema=CandidateDraft)
                span["title"] = draft.title
        except LLMError:
            self.failures += 1
            return None
        return self._card(result, draft)

    def _card(self, result: LoopResult, draft: CandidateDraft) -> KnowledgeCard:
        # Content-addressed id: the same round written up in the same words is
        # the same candidate, so a re-run deduplicates instead of accumulating.
        digest = hashlib.sha256(draft.body.encode("utf-8")).hexdigest()[:8]
        slug = result.case_id.lower().replace("_", "-")
        return KnowledgeCard(
            id=f"loop-{slug}-{digest}",
            title=draft.title,
            body=draft.body,
            source_title=f"闭环复盘：案例 {result.case_id}（合成）",
            source_url="",  # the round is the source, and it has no URL to fake
            license="CC-BY-4.0（本项目合成案例复盘）",
            retrieved_at=date.today().isoformat(),
            applicable_material=(result.report.material,),
            evidence_level=EvidenceLevel.CASE_HISTORY,
            tags=draft.tags,
        )


def write_candidate(card: KnowledgeCard, root: Path | None = None) -> Path | None:
    """Persist into the quarantine. Returns ``None`` if the card already exists.

    Never overwrites: a file under review must not change beneath its reviewer.
    There is no ``write_accepted`` and there must never be one — promotion is a
    manual move (``knowledge/README.md``), not an API this module could be
    talked into calling.
    """
    folder = (root or KNOWLEDGE_ROOT) / CANDIDATE
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{card.id}.md"
    if path.exists():
        return None

    front = {
        "id": card.id,
        "title": card.title,
        "source_title": card.source_title,
        "source_url": card.source_url,
        "license": card.license,
        "retrieved_at": card.retrieved_at,
        "applicable_material": list(card.applicable_material),
        "evidence_level": card.evidence_level.value,
        "tags": list(card.tags),
    }
    rendered = yaml.safe_dump(front, allow_unicode=True, sort_keys=False)
    path.write_text(f"---\n{rendered}---\n\n{card.body}\n", encoding="utf-8")
    return path
