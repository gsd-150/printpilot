"""The SafetyGate: the last thing between a proposal and the machine.

Pure Python. No model call, no retrieval, no judgement that cannot be read off the
rules below. An LLM may *propose*; only this decides.

## Why the label-consistency rules are not enough

The obvious design checks that the action agrees with the diagnosis: diagnosed a
clog, do not send a parameter patch. That catches an incoherent agent, and it is
worth having — but it does not catch the failure actually measured on holdout.

There, ``llm+skills`` routed 10% of clogs onto the parameter path. Those were not
incoherent: the model believed it was looking at a parameter fault and proposed a
patch entirely consistent with that belief. A gate that only checks
diagnosis-against-action approves every one of them, because they *are* consistent.
The error is upstream, in the diagnosis, and a gate reading the diagnosis inherits
it.

So SG-6 does not read the diagnosis at all. It reads the **features** — and if a
mechanical signature is present, no parameter patch is permitted regardless of what
anything upstream concluded. This is how interlocks work on real machines: they do
not ask the controller for its opinion, they trip on the sensor.

The threshold is deliberately more conservative than the one the rules diagnoser
uses to *call* a clog. An interlock should trip early; a false trip costs a
needless pause, a missed one costs a nozzle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from printpilot.domain import (
    FAULT_CATALOG,
    HARDWARE_BOUNDS,
    ActionPlan,
    ActionType,
    DiagnosisResult,
    FaultCode,
    ParamName,
    PhenomenonReport,
    RemediationClass,
    RiskLevel,
    SafetyDecision,
    SafetyVerdict,
)
from printpilot.domain.process_windows import window_for

#: Extruder-current rise above which a parameter patch is refused, whatever the
#: diagnosis says. Lower than the rules diagnoser's 0.023 threshold for *calling*
#: a partial clog: the interlock should trip before the diagnosis is confident.
INTERLOCK_CURRENT_RISE: Final = 0.015

#: Tail flow below which nothing is coming out and no patch can help.
INTERLOCK_FLOW_COLLAPSE: Final = 0.30

#: Below this diagnostic confidence, an action needs a human.
MIN_CONFIDENCE_FOR_AUTONOMY: Final = 0.60

PARAM_ACTIONS: Final = frozenset({ActionType.APPLY_PARAM_PATCH})


@dataclass(frozen=True)
class GateContext:
    """Everything the gate is allowed to look at."""

    plan: ActionPlan
    diagnosis: DiagnosisResult
    report: PhenomenonReport
    current_params: dict[ParamName, float]
    material: str


def _feature(report: PhenomenonReport, name: str) -> float | None:
    found = report.feature(name)
    return found.value if found else None


def review(context: GateContext) -> SafetyVerdict:
    """Rule the proposal in, out, or up to a human."""
    violations: list[str] = []
    notes: list[str] = []
    escalate = False

    plan = context.plan
    wants_patch = plan.action_type in PARAM_ACTIONS

    # SG-1 — a fault whose remediation is not parameter-based may not take the
    # parameter path, however the plan justifies it.
    top = context.diagnosis.top.fault_code
    remediation = FAULT_CATALOG[top].remediation
    if wants_patch and remediation is not RemediationClass.PARAM_FIXABLE:
        violations.append(f"SG-1: 诊断为 {top.value}（{remediation.value}），不得下发参数补丁")

    # SG-2 — parameters this fault forbids raising, may not be raised.
    forbidden = FAULT_CATALOG[top].forbidden_increase
    for delta in plan.patch:
        if delta.param in forbidden and delta.delta > 0:
            violations.append(
                f"SG-2: {top.value} 禁止提高 {delta.param.value}（提议 +{delta.delta:g}）"
            )

    # SG-3 — hardware limits. Absolute, and applied to the resulting value, not
    # just the step.
    for delta in plan.patch:
        bound = HARDWARE_BOUNDS[delta.param]
        if abs(delta.delta) > bound.max_abs_delta:
            violations.append(
                f"SG-3: {delta.param.value} 单步变更 {delta.delta:+g} 超过上限 "
                f"{bound.max_abs_delta:g}"
            )
        current = context.current_params.get(delta.param)
        if current is None:
            violations.append(f"SG-3: 缺少 {delta.param.value} 的当前值，无法校验结果是否越界")
            continue
        result = current + delta.delta
        if not (bound.min_value <= result <= bound.max_value):
            violations.append(
                f"SG-3: {delta.param.value} 将变为 {result:g}，超出硬件边界 "
                f"[{bound.min_value:g}, {bound.max_value:g}]"
            )

    # SG-4 — low confidence, or a plan that calls itself risky, needs a human.
    if wants_patch and context.diagnosis.top.confidence < MIN_CONFIDENCE_FOR_AUTONOMY:
        escalate = True
        notes.append(f"SG-4: 诊断置信度 {context.diagnosis.top.confidence:.2f} 低于自主执行门槛")
    if plan.risk_level is RiskLevel.HIGH and not plan.requires_approval:
        escalate = True
        notes.append("SG-4: 高风险动作必须标记为需要审批")

    # SG-5 — an abstention is not a mandate.
    if top is FaultCode.UNKNOWN and plan.action_type not in {
        ActionType.ESCALATE_TO_HUMAN,
        ActionType.NO_ACTION,
        ActionType.PAUSE_AND_INSPECT,
    }:
        violations.append("SG-5: 诊断为 UNKNOWN 时不得执行自动动作")

    # SG-6 — the evidence interlock. Reads features, never the diagnosis.
    if wants_patch:
        violations += _mechanical_interlock(context)

    # Advisory: outside the material's published window is a warning, not a refusal.
    for delta in plan.patch:
        current = context.current_params.get(delta.param)
        window = window_for(context.material, delta.param)
        if current is not None and window and not window.contains(current + delta.delta):
            notes.append(
                f"注意：{delta.param.value} 将变为 {current + delta.delta:g}，"
                f"超出 {context.material} 推荐工艺窗口 [{window.low:g}, {window.high:g}]"
            )

    if violations:
        decision = SafetyDecision.BLOCK
    elif escalate:
        decision = SafetyDecision.ESCALATE
    else:
        decision = SafetyDecision.ALLOW

    return SafetyVerdict(
        case_id=plan.case_id,
        decision=decision,
        violated_rules=violations,
        notes=" | ".join(notes),
    )


def _mechanical_interlock(context: GateContext) -> list[str]:
    """Refuse parameter patches whenever the raw signals show mechanical trouble.

    Deliberately independent of the diagnosis. This is the rule that catches a
    *misdiagnosed* clog, which is the failure mode the holdout run exposed and
    which no consistency check can reach.
    """
    violations: list[str] = []
    report = context.report

    current_delta = _feature(report, "current_delta")
    if current_delta is not None and current_delta > INTERLOCK_CURRENT_RISE:
        violations.append(
            f"SG-6: 挤出机电流上升 {current_delta:+.4f} 超过联锁阈值 "
            f"{INTERLOCK_CURRENT_RISE:g}，存在机械阻力迹象，禁止参数补偿"
            "（本规则不读取诊断结论）"
        )

    flow_tail = _feature(report, "flow_tail_mean")
    if flow_tail is not None and flow_tail < INTERLOCK_FLOW_COLLAPSE:
        violations.append(
            f"SG-6: 尾段流量比 {flow_tail:.3f} 低于 {INTERLOCK_FLOW_COLLAPSE:g}，"
            "挤出已基本停止，参数补偿无从生效"
        )

    if "current_delta" in report.uncomputable_features:
        violations.append(
            "SG-6: 判别信号 extruder_current 缺失，无法排除机械阻力，不得在此前提下下发参数补丁"
        )

    return violations
