"""The pipeline as an actual ``StateGraph``.

Assembles perceive → diagnose → decide → safety_gate → execute, with the
graph's only conditional edge exactly where the architecture claims one: the
gate's ruling decides whether anything executes. Every node is wrapped in
:func:`validating_node`, so the M2 finding — LangGraph does not validate what
a node writes back — is guarded on the production path, not only in the smoke
test.

Two deliberate scope limits. The simulation on either side of a round
(re-printing, independent quality judging) stays outside the graph: it is the
harness measuring the pipeline, not part of it. And the eval runner does not
route through the graph either — it evaluates *diagnosers*, and wrapping each
in a five-node graph would measure the wrapper, not the arm.

Node ids are verbs ("diagnose") while state keys are nouns ("diagnosis"):
LangGraph refuses a node named after a state key, which is why these differ.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from printpilot.decision import decide
from printpilot.diagnosis import diagnose
from printpilot.domain import (
    ActionPlan,
    ActionType,
    DiagnosisResult,
    ParamName,
    PhenomenonReport,
    SafetyDecision,
    SafetyVerdict,
)
from printpilot.execution.apply import ExecutionResult, Executor
from printpilot.perception import perceive
from printpilot.safety import GateContext, review
from printpilot.simulator import Telemetry
from printpilot.workflow.validation import (
    NodeContractError,
    StateNodeFn,
    StateUpdate,
    validating_node,
)

type Diagnoser = Callable[[PhenomenonReport], DiagnosisResult]
type Decider = Callable[[DiagnosisResult, PhenomenonReport], ActionPlan]


class PipelineState(BaseModel):
    """One round's state channel. Inputs are required; every stage's output is
    ``None`` until its node has run, so the state doubles as a record of how
    far the round got."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    material: str
    current_params: dict[ParamName, float]
    telemetry: Telemetry
    report: PhenomenonReport | None = None
    diagnosis: DiagnosisResult | None = None
    plan: ActionPlan | None = None
    verdict: SafetyVerdict | None = None
    execution: ExecutionResult | None = None


def _require[T](value: T | None, node: str, needs: str) -> T:
    if value is None:
        msg = f"node {node!r} ran before {needs!r} was produced; the graph's edges are wrong"
        raise NodeContractError(msg)
    return value


def _perceive(state: PipelineState) -> StateUpdate:
    return {"report": perceive(state.telemetry, material=state.material)}


def _diagnose_with(diagnoser: Diagnoser) -> StateNodeFn[PipelineState]:
    def _diagnose(state: PipelineState) -> StateUpdate:
        return {"diagnosis": diagnoser(_require(state.report, "diagnose", "report"))}

    return _diagnose


def _decide_with(decider: Decider) -> StateNodeFn[PipelineState]:
    def _decide(state: PipelineState) -> StateUpdate:
        diagnosis = _require(state.diagnosis, "decide", "diagnosis")
        report = _require(state.report, "decide", "report")
        return {"plan": decider(diagnosis, report)}

    return _decide


def _safety_gate(state: PipelineState) -> StateUpdate:
    context = GateContext(
        plan=_require(state.plan, "safety_gate", "plan"),
        diagnosis=_require(state.diagnosis, "safety_gate", "diagnosis"),
        report=_require(state.report, "safety_gate", "report"),
        current_params=state.current_params,
        material=state.material,
    )
    return {"verdict": review(context)}


def _execute(state: PipelineState) -> StateUpdate:
    result = Executor().apply(
        _require(state.plan, "execute", "plan"),
        _require(state.verdict, "execute", "verdict"),
        state.current_params,
    )
    return {"execution": result}


def _route(state: PipelineState) -> Literal["execute", "stop"]:
    """Only an allowed parameter patch has anything to execute; every other
    combination ends the round with the verdict on record."""
    verdict = _require(state.verdict, "route", "verdict")
    plan = _require(state.plan, "route", "plan")
    allowed = verdict.decision is SafetyDecision.ALLOW
    return "execute" if allowed and plan.action_type is ActionType.APPLY_PARAM_PATCH else "stop"


def build_pipeline(*, diagnoser: Diagnoser = diagnose, decider: Decider = decide) -> Any:
    """Assemble and compile the round pipeline.

    Defaults are the rules arms; pass an :class:`~printpilot.diagnosis.llm.LLMDiagnoser`
    or :class:`~printpilot.decision.llm.LLMDecider` to swap a node — the gate
    reviews whatever the decider proposed, which is the point of the shape.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("perceive", validating_node(PipelineState, _perceive))
    graph.add_node("diagnose", validating_node(PipelineState, _diagnose_with(diagnoser)))
    graph.add_node("decide", validating_node(PipelineState, _decide_with(decider)))
    graph.add_node("safety_gate", validating_node(PipelineState, _safety_gate))
    graph.add_node("execute", validating_node(PipelineState, _execute))

    graph.add_edge(START, "perceive")
    graph.add_edge("perceive", "diagnose")
    graph.add_edge("diagnose", "decide")
    graph.add_edge("decide", "safety_gate")
    graph.add_conditional_edges("safety_gate", _route, {"execute": "execute", "stop": END})
    graph.add_edge("execute", END)
    return graph.compile()


_DEFAULT_PIPELINE: Any | None = None


def default_pipeline() -> Any:
    """The all-rules pipeline, compiled once and reused across rounds."""
    global _DEFAULT_PIPELINE
    if _DEFAULT_PIPELINE is None:
        _DEFAULT_PIPELINE = build_pipeline()
    return _DEFAULT_PIPELINE


def run_pipeline(state: PipelineState, *, graph: Any | None = None) -> PipelineState:
    """Invoke the graph and hand back a validated state.

    ``invoke`` returns a plain dict rather than the state model — pinned by
    ``test_langgraph_smoke.py`` — so the result is re-validated here instead of
    trusting attribute access to fail loudly later.
    """
    compiled = default_pipeline() if graph is None else graph
    return PipelineState.model_validate(compiled.invoke(state))
