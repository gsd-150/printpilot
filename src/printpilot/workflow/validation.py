"""Node-boundary validation.

LangGraph accepts a Pydantic model as the state schema, but it validates that
schema only when the graph is *invoked* — not when a node writes back. Verified
against langgraph 1.2.10 (see ``docs/decisions/0001-agent-framework.md``):

* a node returning an unknown key has that key silently dropped;
* a node returning the **wrong type** for a known key has it silently accepted,
  leaving the state holding a value its own schema forbids.

The second case matters here. This project's argument is that nodes exchange
validated structures rather than prose; a channel that lets a node write a string
into a float field would quietly undermine exactly that. So every node is wrapped
and its proposed update is validated against the schema before it lands.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

type StateUpdate = Mapping[str, Any] | None


class StateNodeFn[StateT: BaseModel](Protocol):
    """A LangGraph node.

    Declared as a callback Protocol rather than ``Callable[[StateT], StateUpdate]``
    because LangGraph's own node Protocol names the parameter ``state``. A bare
    ``Callable`` is positional-only and therefore not assignable to it, which
    ``StateGraph.add_node`` rejects at type-check time.
    """

    def __call__(self, state: StateT) -> StateUpdate: ...


class NodeContractError(RuntimeError):
    """A node proposed a state update its schema does not permit.

    Raised loudly and immediately: a contract violation here is a bug in one of
    our own nodes, not a runtime condition to degrade around. Degradation is for
    external failures such as an LLM timeout.
    """


def validating_node[StateT: BaseModel](
    state_type: type[StateT],
    fn: StateNodeFn[StateT],
) -> StateNodeFn[StateT]:
    """Wrap ``fn`` so its partial update is checked against ``state_type``.

    The update is merged onto the current state and the result re-validated, which
    catches both unknown keys (models set ``extra="forbid"``) and wrong types.
    """
    name = getattr(fn, "__name__", type(fn).__name__)

    def wrapper(state: StateT) -> StateUpdate:
        update = fn(state)
        if update is None:
            return None

        merged = {**state.model_dump(), **dict(update)}
        try:
            state_type.model_validate(merged)
        except ValidationError as exc:
            msg = f"node {name!r} proposed an invalid update to {state_type.__name__}"
            raise NodeContractError(msg) from exc
        return update

    return wrapper
