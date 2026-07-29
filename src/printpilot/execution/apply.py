"""Execution: applying an allowed plan.

Pure Python, and the only place parameters actually change. The LLM never writes
here — it produces an :class:`ActionPlan`, the gate rules on it, and this applies
what survived. Keeping the write deterministic is what makes the change auditable
and the rollback exact.

Execution re-checks the verdict rather than trusting the caller to have done so.
The order "review then apply" is easy to get wrong once there are branches, and a
skipped review is not a mistake that announces itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from printpilot.domain import (
    ActionPlan,
    ActionType,
    ParamName,
    SafetyDecision,
    SafetyVerdict,
)


class ExecutionRefusedError(RuntimeError):
    """An attempt to apply a plan the gate did not allow."""


@dataclass(frozen=True)
class ParamChange:
    param: ParamName
    before: float
    after: float

    def __str__(self) -> str:
        return f"{self.param.value}: {self.before:g} -> {self.after:g}"


@dataclass(frozen=True)
class ExecutionResult:
    """What changed, and how to undo it."""

    case_id: str
    applied: bool
    params: dict[ParamName, float]
    changes: tuple[ParamChange, ...] = ()
    reason: str = ""

    @property
    def diff(self) -> str:
        return "; ".join(str(c) for c in self.changes) if self.changes else "(无变更)"

    def rollback(self) -> dict[ParamName, float]:
        """Exact inverse. Derived from the recorded before-values rather than by
        re-subtracting the deltas, so it stays correct if a delta was clamped."""
        restored = dict(self.params)
        for change in self.changes:
            restored[change.param] = change.before
        return restored


@dataclass
class Executor:
    """Applies allowed plans; records everything it did."""

    history: list[ExecutionResult] = field(default_factory=list)

    def apply(
        self,
        plan: ActionPlan,
        verdict: SafetyVerdict,
        current: dict[ParamName, float],
    ) -> ExecutionResult:
        if verdict.decision is not SafetyDecision.ALLOW:
            msg = (
                f"plan for {plan.case_id} was {verdict.decision.value}, not allowed: "
                f"{'; '.join(verdict.violated_rules) or verdict.notes}"
            )
            raise ExecutionRefusedError(msg)

        if plan.action_type is not ActionType.APPLY_PARAM_PATCH:
            result = ExecutionResult(
                case_id=plan.case_id,
                applied=False,
                params=dict(current),
                reason=f"{plan.action_type.value} 不改变参数",
            )
            self.history.append(result)
            return result

        updated = dict(current)
        changes: list[ParamChange] = []
        for delta in plan.patch:
            before = updated[delta.param]
            after = before + delta.delta
            updated[delta.param] = after
            changes.append(ParamChange(param=delta.param, before=before, after=after))

        result = ExecutionResult(
            case_id=plan.case_id,
            applied=True,
            params=updated,
            changes=tuple(changes),
            reason=plan.rationale,
        )
        self.history.append(result)
        return result
