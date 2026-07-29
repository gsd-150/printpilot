"""Rules-only diagnosis baseline.

This is the control arm of the ablation. Its job is to be a *fair* baseline: an
LLM configuration that cannot beat plain thresholds is not earning its cost, and
a deliberately weak baseline would make every later number look better than it is.

The rules encode the same reasoning the domain notes describe — flow shortfall
says *something* is under-extruding, extruder current says *why* — so the question
the ablation actually asks is whether a model adds anything beyond that.

It also serves as the degraded path: when the LLM is unavailable, this runs
instead, and the run is marked ``degraded`` rather than failed.
"""

from __future__ import annotations

from printpilot.domain import (
    DiagnosisResult,
    EvidenceKind,
    EvidenceRef,
    FaultCode,
    Hypothesis,
    PhenomenonReport,
)
from printpilot.perception.calibration import NOMINAL_BANDS

#: Current rise above which mechanical resistance is the better explanation.
#: Midway between the nominal envelope's upper edge (+0.008) and where partial
#: clogs begin in dev (+0.038), so neither class sits on the boundary.
CURRENT_RISE_THRESHOLD = 0.023

#: Current *drop* this large means the drive is no longer pushing against anything.
CURRENT_COLLAPSE_THRESHOLD = -0.05

#: Below this tail flow, essentially nothing is coming out.
FLOW_COLLAPSE_THRESHOLD = 0.20

DIAGNOSER_NAME = "rules-only"


def _feature(report: PhenomenonReport, name: str) -> float | None:
    found = report.feature(name)
    return found.value if found else None


def _signal_evidence(report: PhenomenonReport, name: str) -> EvidenceRef:
    value = _feature(report, name)
    return EvidenceRef(
        kind=EvidenceKind.SIGNAL,
        ref=name,
        detail=f"{value:.4f}" if value is not None else "unavailable",
    )


def _abstain(report: PhenomenonReport, reason: str) -> DiagnosisResult:
    return DiagnosisResult(
        case_id=report.case_id,
        hypotheses=[Hypothesis(fault_code=FaultCode.UNKNOWN, confidence=0.5, reasoning=reason)],
    )


def diagnose(report: PhenomenonReport) -> DiagnosisResult:
    """Classify from thresholds alone."""
    flow_tail = _feature(report, "flow_tail_mean")
    if flow_tail is None:
        return _abstain(report, "缺少 flow_ratio 信号，无法判断挤出状态。")

    tail_deficit = _feature(report, "flow_tail_deficit_fraction") or 0.0
    current_delta = _feature(report, "current_delta")
    temp_deviation = _feature(report, "temp_deviation_tail")

    # 1. Flow has collapsed: nothing is being extruded. Current direction only
    #    corroborates; the flow reading alone is already decisive.
    if flow_tail < FLOW_COLLAPSE_THRESHOLD:
        return _one(
            report,
            FaultCode.CLOG_FULL,
            0.95,
            "尾段流量比接近 0，挤出已停止。",
            ["flow_tail_mean", "current_delta"],
        )

    sustained = tail_deficit > (NOMINAL_BANDS["flow_tail_deficit_fraction"].high or 0.32)
    short = sustained and flow_tail < (NOMINAL_BANDS["flow_tail_mean"].low or 0.985)

    # 2. A mechanical signature settles the question on its own, whatever the
    #    temperature is doing, so it is tested before the thermal branch.
    if short and current_delta is not None:
        if current_delta > CURRENT_RISE_THRESHOLD:
            return _one(
                report,
                FaultCode.CLOG_PARTIAL,
                0.85,
                "流量持续偏低且挤出机电流随之上升，指向机械阻力增大。",
                ["flow_tail_mean", "current_delta"],
            )
        if current_delta < CURRENT_COLLAPSE_THRESHOLD:
            return _one(
                report,
                FaultCode.CLOG_FULL,
                0.80,
                "电流大幅下降，驱动已不再推动料丝。",
                ["flow_tail_mean", "current_delta"],
            )

    # 3. No mechanical signature, but temperature is off setpoint. Running outside
    #    the material's window depresses extrusion by itself, so the thermal fault
    #    explains a mild shortfall — and it must be tested before attributing that
    #    shortfall to a flow setting, or every thermal case is absorbed as one.
    if temp_deviation is not None and temp_deviation > (
        NOMINAL_BANDS["temp_deviation_tail"].high or 0.045
    ):
        return _one(
            report,
            FaultCode.THERMAL_DRIFT,
            0.80,
            "热端温度持续偏离设定值，且无机械阻力上升的迹象。",
            ["temp_deviation_tail", "flow_tail_mean"],
        )

    # 4. Sustained shortfall, resistance normal, temperature in window.
    if short:
        if current_delta is None:
            return _abstain(
                report,
                "存在持续性欠挤出，但缺少 extruder_current，"
                "无法区分机械堵塞与参数性欠挤出——两者处置相反，不应猜测。",
            )
        return _one(
            report,
            FaultCode.UNDEREXT_PARAM,
            0.80,
            "流量持续偏低但电流未升高、温度在窗口内，指向 flow 设定偏低。",
            ["flow_tail_mean", "current_delta"],
        )

    # 5. Dips that recovered. Doing nothing is an answer, not a failure to decide.
    return _one(
        report,
        FaultCode.NORMAL_SUSPICIOUS,
        0.75,
        "流量存在瞬时凹陷但已恢复，且无持续性偏差，无需干预。",
        ["flow_tail_mean", "flow_tail_deficit_fraction"],
    )


def _one(
    report: PhenomenonReport,
    fault: FaultCode,
    confidence: float,
    reasoning: str,
    evidence: list[str],
) -> DiagnosisResult:
    return DiagnosisResult(
        case_id=report.case_id,
        hypotheses=[
            Hypothesis(
                fault_code=fault,
                confidence=confidence,
                reasoning=reasoning,
                evidence=[
                    _signal_evidence(report, name)
                    for name in evidence
                    if report.feature(name) is not None
                ],
            )
        ],
    )
