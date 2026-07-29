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
from collections.abc import Sequence
from dataclasses import dataclass, field

from printpilot.domain import DiagnosisResult, FaultCode, Hypothesis, PhenomenonReport
from printpilot.harness.trace import DISABLED, Step, Tracer
from printpilot.llm.base import LLMClient, LLMError
from printpilot.prompts import Prompt, load_prompt
from printpilot.rag import KnowledgeStore, Retrieved
from printpilot.skills_runtime import RouteMatch, SkillRegistry

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


def render_skills(matches: Sequence[RouteMatch]) -> str:
    """Lay out the selected Skills for injection.

    Each carries *why it was selected* and whether it is operating with a signal
    missing. A Skill that reached the prompt in degraded form is giving advice
    about a case it can only partly see, and saying so is the difference between
    "here is the procedure" and "here is the procedure, and you are missing an
    input it relies on".
    """
    if not matches:
        return ""

    blocks = ["\n\n---\n\n# 适用的领域技能\n"]
    for match in matches:
        note = (
            f"（**降级**：缺少 {', '.join(match.missing_optional)}，结论的确定性相应下降）"
            if match.degraded
            else ""
        )
        blocks.append(
            f"\n## {match.skill.name} v{match.skill.meta.version}\n"
            f"\n选中依据：越界特征 {', '.join(match.satisfied_triggers)}{note}\n\n"
            f"{match.skill.body}\n"
        )
    return "".join(blocks)


def render_knowledge(passages: Sequence[Retrieved]) -> str:
    """Lay out retrieved passages, each with its provenance.

    Citing the source is not decoration. The priority chain says a sourced RAG
    passage outranks the model's own prior and is outranked by a reviewed Skill —
    a passage arriving without its evidence level cannot be placed in that order.
    """
    if not passages:
        return ""

    blocks = ["\n\n---\n\n# 检索到的知识\n"]
    for passage in passages:
        blocks.append(
            f"\n## {passage.title}\n"
            f"\n来源：{passage.source_label}｜相似度 {passage.score:.3f}\n\n"
            f"{passage.body}\n"
        )
    blocks.append("\n（以上为检索证据。优先级低于经审核的 Skill，高于模型自身知识。）\n")
    return "".join(blocks)


#: Feature name plus direction, rendered as the phrase a person would use.
#:
#: The first version of the query was ``"flow_tail_mean 0.810；current_delta 0.090"``
#: — the identifiers and their values. It retrieved badly, and the reason is worth
#: keeping: the corpus is prose, and a variable name is not what prose calls a
#: thing. It also meant the retrieval evaluation (written in natural language) was
#: measuring a query distribution the pipeline never produced.
_PHRASES: dict[tuple[str, bool], str] = {
    ("flow_tail_mean", False): "尾段流量比偏低，挤出量不足",
    ("flow_min", False): "流量出现明显下探",
    ("flow_deficit_fraction", True): "大部分层都存在挤出亏损",
    ("flow_tail_deficit_fraction", True): "尾段持续欠挤出，未见恢复",
    ("current_mean", True): "挤出机电流高于正常",
    ("current_mean", False): "挤出机电流低于正常",
    ("current_delta", True): "挤出机电流随打印进程上升，推料阻力增大",
    ("current_delta", False): "挤出机电流随打印进程下降",
    ("temp_deviation_tail", True): "热端温度持续偏离设定值",
    ("temp_bias_tail", True): "热端温度偏高",
    ("temp_bias_tail", False): "热端温度偏低",
}


def phenomenon_query(report: PhenomenonReport) -> str:
    """Turn the case into a retrieval query, in the vocabulary of the corpus.

    Built from the features that are *out of band* plus the ones that could not be
    measured — the anomalies and the blind spots are what knowledge is needed
    about. Querying with every feature would return the whole corpus.
    """
    parts: list[str] = []
    for feature in report.features:
        if not feature.exceeded:
            continue
        above = feature.threshold is not None and feature.value > feature.threshold
        parts.append(
            _PHRASES.get((feature.name, above), f"{feature.name} 异常（{feature.value:.3f}）")
        )

    if report.uncomputable_features:
        parts.append("缺少 " + "、".join(report.uncomputable_features) + "，无法据此判别")
    return "；".join(parts) if parts else "各项特征均在正常带内"


@dataclass
class LLMDiagnoser:
    """Callable with the same shape as the rules baseline, so the eval runner
    treats the two interchangeably.

    ``skills`` is the single variable separating the ``llm`` and ``llm+skills``
    arms. Both use the *same prompt file*; the Skills are appended to the rendered
    prompt rather than living in a second template. A separate template would have
    let wording drift between the arms and quietly become a second variable.

    Safe to call from several threads: the only mutable state is the failure
    counter, which is guarded.
    """

    client: LLMClient
    prompt: Prompt = field(default_factory=lambda: load_prompt(DEFAULT_PROMPT))
    skills: SkillRegistry | None = None
    knowledge: KnowledgeStore | None = None
    top_k: int = 2
    failures: int = 0
    # A shared module-level default would be a mutable default; and a tracer shared
    # between diagnosers would merge two runs' events into one file.
    tracer: Tracer = field(default_factory=lambda: DISABLED)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def name(self) -> str:
        parts = ["llm"]
        if self.knowledge is not None:
            parts.append("rag")
        if self.skills is not None:
            parts.append("skills")
        return f"{'+'.join(parts)}@{self.prompt.name}"

    def __call__(self, report: PhenomenonReport) -> DiagnosisResult:
        rendered = self.prompt.render(phenomenon=render_phenomenon(report))

        # Retrieval before Skills so the injected order runs weakest-evidence
        # first, matching the priority chain the prompt states.
        passages: list[Retrieved] = []
        if self.knowledge is not None:
            with self.tracer.span(report.case_id, Step.RETRIEVAL) as span:
                passages = self.knowledge.query(
                    phenomenon_query(report), top_k=self.top_k, material=report.material
                )
                span["chunks"] = [p.card_id for p in passages]
            rendered += render_knowledge(passages)

        selected: list[RouteMatch] = []
        if self.skills is not None:
            with self.tracer.span(report.case_id, Step.ROUTING) as span:
                selected = self.skills.route(report, top_k=self.top_k)
                span["skills"] = [m.skill.name for m in selected]
                span["degraded"] = [m.skill.name for m in selected if m.degraded]
            rendered += render_skills(selected)
        try:
            with self.tracer.span(report.case_id, Step.DIAGNOSIS, prompt=self.prompt.name) as span:
                result = self.client.complete_structured(prompt=rendered, schema=DiagnosisResult)
                span["predicted"] = result.top.fault_code.value
                span["confidence"] = round(result.top.confidence, 3)
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

        updates: dict[str, object] = {}
        if result.case_id != report.case_id:
            # Models occasionally echo an id from the prompt template. Correcting
            # it here keeps scoring aligned; the model's other output stands.
            updates["case_id"] = report.case_id
        if selected:
            # Recorded from what was actually injected, not from what the model
            # says it used — the latter is a claim, this is a fact.
            updates["skills_used"] = [m.skill.name for m in selected]
        if passages:
            updates["retrieved_chunk_ids"] = [p.card_id for p in passages]
        return result.model_copy(update=updates) if updates else result
