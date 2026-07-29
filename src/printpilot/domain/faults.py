"""Fault catalogue for the synthetic FDM environment.

Scope note (see 项目规划_v2 §1.3): every fault here is observable from *process
telemetry*. Cosmetic/mechanical defects such as warping, stringing and weak
interlayer bonding are deliberately excluded — the available signals indicate
elevated *risk* of those defects, not their occurrence, and claiming otherwise
would overstate what the system can detect.

``CLOG_PARTIAL`` and ``UNDEREXT_PARAM`` look similar on the flow-ratio curve but
call for opposite responses. That pair is the core discrimination task, and the
cost of confusing them is asymmetric: treating a parameter problem as a clog
wastes time, while treating a clog as a parameter problem means increasing flow
into a restricted nozzle — which raises extrusion pressure and grinds filament.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from printpilot.domain.params import ParamName


class FaultCode(StrEnum):
    CLOG_PARTIAL = "CLOG_PARTIAL"
    CLOG_FULL = "CLOG_FULL"
    UNDEREXT_PARAM = "UNDEREXT_PARAM"
    THERMAL_DRIFT = "THERMAL_DRIFT"
    NORMAL_SUSPICIOUS = "NORMAL_SUSPICIOUS"

    # Explicit abstention. A diagnosis that cannot meet its evidence threshold
    # must say so rather than pick the least-bad label; this is what makes the
    # calibration metrics (ECE/Brier) meaningful.
    UNKNOWN = "UNKNOWN"


class RemediationClass(StrEnum):
    """What class of response a fault admits — the safety-critical attribute."""

    PARAM_FIXABLE = "param_fixable"
    MAINTENANCE = "maintenance"
    ABORT = "abort"
    NO_ACTION = "no_action"
    UNDETERMINED = "undetermined"


class FaultSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: FaultCode
    label_zh: str
    remediation: RemediationClass
    observable_signals: tuple[str, ...]
    forbidden_increase: frozenset[ParamName] = Field(
        default=frozenset(),
        description=(
            "Parameters that must never be increased for this fault. Consumed by "
            "the SafetyGate; the LLM cannot override it."
        ),
    )
    rationale: str


FAULT_CATALOG: Final[dict[FaultCode, FaultSpec]] = {
    FaultCode.CLOG_PARTIAL: FaultSpec(
        code=FaultCode.CLOG_PARTIAL,
        label_zh="部分堵塞",
        remediation=RemediationClass.MAINTENANCE,
        observable_signals=("flow_ratio_series", "extruder_current_series"),
        forbidden_increase=frozenset({ParamName.FLOW, ParamName.PRINT_SPEED}),
        rationale=(
            "流量比缓降至 0.6~0.85 且挤出机电流上升。提高 flow 或速度会进一步抬高挤出压力"
            "并加剧磨料，必须先暂停检查。"
        ),
    ),
    FaultCode.CLOG_FULL: FaultSpec(
        code=FaultCode.CLOG_FULL,
        label_zh="完全堵塞",
        remediation=RemediationClass.ABORT,
        observable_signals=("flow_ratio_series",),
        forbidden_increase=frozenset(
            {ParamName.FLOW, ParamName.PRINT_SPEED, ParamName.NOZZLE_TEMP}
        ),
        rationale=(
            "流量比骤降至近 0。无法通过参数补偿继续打印，需停机并进入恢复流动 / cold pull / "
            "拆检流程。"
        ),
    ),
    FaultCode.UNDEREXT_PARAM: FaultSpec(
        code=FaultCode.UNDEREXT_PARAM,
        label_zh="参数性欠挤出",
        remediation=RemediationClass.PARAM_FIXABLE,
        observable_signals=("flow_ratio_series", "extruder_current_series"),
        rationale=(
            "流量比 0.85~0.95 但挤出机电流正常——机械阻力未升高，指向 flow 设定偏低或温度"
            "偏低，可通过参数调整修复。"
        ),
    ),
    FaultCode.THERMAL_DRIFT: FaultSpec(
        code=FaultCode.THERMAL_DRIFT,
        label_zh="热端温度漂移",
        remediation=RemediationClass.PARAM_FIXABLE,
        observable_signals=("hotend_temp_series", "hotend_duty_series"),
        rationale="实测温度偏离设定值且加热占空比异常，可通过温度/风扇参数修正。",
    ),
    FaultCode.NORMAL_SUSPICIOUS: FaultSpec(
        code=FaultCode.NORMAL_SUSPICIOUS,
        label_zh="正常但可疑",
        remediation=RemediationClass.NO_ACTION,
        observable_signals=("flow_ratio_series",),
        rationale=("换料、几何切换或启动瞬态引起的正常波动。假阳性陷阱：正确响应是不动作。"),
    ),
    FaultCode.UNKNOWN: FaultSpec(
        code=FaultCode.UNKNOWN,
        label_zh="证据不足",
        remediation=RemediationClass.UNDETERMINED,
        observable_signals=(),
        rationale="证据不足以支持任何具体根因，应升级至人工判断而非猜测。",
    ),
}


def remediation_for(code: FaultCode) -> RemediationClass:
    """Look up how a fault may be responded to."""
    return FAULT_CATALOG[code].remediation
