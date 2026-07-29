"""LangGraph workflow assembly.

The graph itself lands in M4; this package currently holds the node-boundary
validation that the M2 framework evaluation showed was necessary.
"""

from __future__ import annotations

from printpilot.workflow.validation import (
    NodeContractError,
    StateNodeFn,
    StateUpdate,
    validating_node,
)

__all__ = ["NodeContractError", "StateNodeFn", "StateUpdate", "validating_node"]
