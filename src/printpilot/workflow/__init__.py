"""Workflow: the LangGraph pipeline assembly, and the node-boundary validation.

``graph`` assembles perceive → diagnose → decide → safety_gate → execute into
a ``StateGraph`` whose only conditional edge routes on the gate's verdict; the
closed loop runs every round through it. ``validation`` guards what nodes
write back — the M2 finding that LangGraph re-validates state only at
``invoke()`` — and every node in the assembly is wrapped in it.
"""

from __future__ import annotations

from printpilot.workflow.graph import (
    Decider,
    Diagnoser,
    PipelineState,
    build_pipeline,
    default_pipeline,
    run_pipeline,
)
from printpilot.workflow.validation import (
    NodeContractError,
    StateNodeFn,
    StateUpdate,
    validating_node,
)

__all__ = [
    "Decider",
    "Diagnoser",
    "NodeContractError",
    "PipelineState",
    "StateNodeFn",
    "StateUpdate",
    "build_pipeline",
    "default_pipeline",
    "run_pipeline",
    "validating_node",
]
