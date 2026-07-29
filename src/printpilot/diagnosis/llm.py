"""LLM-backed diagnosis.

What this configuration deliberately does **not** get is domain knowledge. The
baseline prompt supplies measured values and the nominal band each was compared
against, plus the list of valid fault codes — and nothing about what a clog looks
like or which signal separates it from a low flow setting.

That omission is the point. If the discrimination heuristics were written into
the prompt, the later ``+RAG`` and ``+Skills`` configurations would have nothing
left to contribute and the ablation would measure nothing. The knowledge belongs
in the layers being ablated, not in the control.

An honest caveat, worth stating before anyone reads the numbers: the fault code
names themselves (``CLOG_PARTIAL``, ``UNDEREXT_PARAM``) carry meaning, and a
capable model will infer a good deal from them. The baseline is therefore not
knowledge-free; it is knowledge-*minimal*.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from printpilot.domain import DiagnosisResult, FaultCode, Hypothesis, PhenomenonReport
from printpilot.llm.base import LLMClient, LLMError
from printpilot.prompts import Prompt, load_prompt

DEFAULT_PROMPT = "diagnosis/v1_baseline"


def render_phenomenon(report: PhenomenonReport) -> str:
    """Lay out the case for the model.

    Only what perception measured. No family id, no split, no label — see
    ``PhenomenonReport`` for why that field does not exist.
    """
    lines = [
        f"case_id: {report.case_id}",
        f"material: {report.material}",
        "",
        "Derived features (value against the band seen on healthy prints):",
    ]
    for feature in report.features:
        flag = "  <-- outside nominal" if feature.exceeded else ""
        bound = f"{feature.threshold:g}" if feature.threshold is not None else "n/a"
        lines.append(
            f"  {feature.name:<28} {feature.value:>10.4f} {feature.unit:<20}"
            f" nominal bound {bound}{flag}"
        )

    if report.missing_signals:
        lines += ["", f"Signals not present on this printer: {', '.join(report.missing_signals)}"]
    if report.uncomputable_features:
        lines += [
            f"Features that could NOT be measured: {', '.join(report.uncomputable_features)}",
            "(absent, not normal)",
        ]
    return "\n".join(lines)


@dataclass
class LLMDiagnoser:
    """Callable with the same shape as the rules baseline, so the eval runner
    treats the two interchangeably.

    Safe to call from several threads: the only mutable state is the failure
    counter, which is guarded.
    """

    client: LLMClient
    prompt: Prompt = field(default_factory=lambda: load_prompt(DEFAULT_PROMPT))
    failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def name(self) -> str:
        return f"llm@{self.prompt.name}"

    def __call__(self, report: PhenomenonReport) -> DiagnosisResult:
        rendered = self.prompt.render(phenomenon=render_phenomenon(report))
        try:
            result = self.client.complete_structured(prompt=rendered, schema=DiagnosisResult)
        except LLMError as exc:
            # Abstain rather than crash the run. A transport failure is not
            # evidence about the print, and silently substituting a guess would
            # contaminate the metrics with the network's behaviour.
            with self._lock:
                self.failures += 1
            return DiagnosisResult(
                case_id=report.case_id,
                hypotheses=[
                    Hypothesis(
                        fault_code=FaultCode.UNKNOWN,
                        confidence=0.0,
                        reasoning=f"诊断调用失败，未作判断：{exc}",
                    )
                ],
            )

        if result.case_id != report.case_id:
            # Models occasionally echo an id from the prompt template. Correcting
            # it here keeps scoring aligned; the model's other output stands.
            result = result.model_copy(update={"case_id": report.case_id})
        return result
