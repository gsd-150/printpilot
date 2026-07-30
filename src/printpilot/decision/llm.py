"""LLM-backed decision: the ablation arm for "the LLM may propose".

The rules decider stays the default, and on current evidence deserves to: the
fault→remediation mapping is a lookup plus a conservative step size, which is
rule-shaped work. What this arm buys is a measurement. "An LLM may propose but
cannot release" is, without it, an architecture claim backed by one replay
experiment; with it, the SafetyGate's interception of live LLM proposals is a
per-round count.

Deliberately knowledge-minimal, for the same reason as the diagnosis baseline:
the prompt states the output contract and the action vocabulary, not which
fault routes where. Feeding the decider the routing table would measure the
prompt author; the gate exists precisely so safety does not depend on any
upstream stage knowing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from printpilot.diagnosis.llm import render_phenomenon
from printpilot.domain import (
    ActionPlan,
    ActionType,
    DiagnosisResult,
    PhenomenonReport,
    RiskLevel,
)
from printpilot.harness.trace import DISABLED, Step, Tracer
from printpilot.llm.base import LLMClient, LLMError
from printpilot.prompts import Prompt, load_prompt

DEFAULT_PROMPT = "decision/v1_baseline"


def render_diagnosis(diagnosis: DiagnosisResult) -> str:
    """Lay out the upstream stage's conclusion, evidence attached.

    The decider sees the hypotheses as ranked, not just the winner: a close
    second place is exactly the situation where escalating beats acting.
    """
    lines = [f"case_id: {diagnosis.case_id}", "", "Ranked hypotheses from the diagnosis stage:"]
    for hyp in diagnosis.hypotheses:
        refs = ", ".join(e.ref for e in hyp.evidence) or "none"
        lines.append(
            f"  {hyp.fault_code.value:<20} confidence {hyp.confidence:.2f}  evidence: {refs}"
        )
        if hyp.reasoning:
            lines.append(f"    reasoning: {hyp.reasoning}")
    return "\n".join(lines)


@dataclass
class LLMDecider:
    """Callable with the same shape as the rules decider, so the pipeline graph
    swaps one for the other without knowing which it holds.

    On transport failure it escalates instead of guessing: a network error is
    not evidence about the print, and the one action that is safe to propose
    without evidence is handing the case to a human.
    """

    client: LLMClient
    prompt: Prompt = field(default_factory=lambda: load_prompt(DEFAULT_PROMPT))
    tracer: Tracer = field(default_factory=lambda: DISABLED)
    failures: int = 0

    @property
    def name(self) -> str:
        return f"llm@{self.prompt.name}"

    def __call__(self, diagnosis: DiagnosisResult, report: PhenomenonReport) -> ActionPlan:
        rendered = self.prompt.render(
            diagnosis=render_diagnosis(diagnosis),
            phenomenon=render_phenomenon(report),
        )
        try:
            with self.tracer.span(
                diagnosis.case_id, Step.DECISION, prompt=self.prompt.name
            ) as span:
                plan = self.client.complete_structured(prompt=rendered, schema=ActionPlan)
                span["action"] = plan.action_type.value
        except LLMError as exc:
            self.failures += 1
            return ActionPlan(
                case_id=diagnosis.case_id,
                action_type=ActionType.ESCALATE_TO_HUMAN,
                rationale=f"决策调用失败，未作提议，升级人工：{exc}",
                evidence_refs=list(diagnosis.top.evidence),
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                rollback_plan="无变更，无需回滚。",
            )

        if plan.case_id != diagnosis.case_id:
            # Same correction as the diagnoser: models occasionally echo an id
            # from the prompt template; scoring and tracing key on the real one.
            plan = plan.model_copy(update={"case_id": diagnosis.case_id})
        return plan
