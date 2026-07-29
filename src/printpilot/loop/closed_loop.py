"""One round of perceive → diagnose → decide → gate → execute → re-print → judge.

The last step is the one that makes this a loop rather than a pipeline: after the
settings change, the print is simulated again and scored by
:func:`printpilot.simulator.evaluate_quality`, which sees only telemetry. It never
learns what fault was injected, what was diagnosed, or what was changed — so
"did it help?" is answered by an outcome measurement rather than by asking whether
the fault flag cleared, which would only check the generator against itself.

Three outcomes are distinguished, and the third is why the physics matters:

* **improved** — quality rose.
* **unchanged** — within the noise band, or no action was taken.
* **harmed** — quality fell. Raising flow into a restriction does exactly this,
  so a loop that patches a misdiagnosed clog is measured as *doing damage*, not
  merely as failing to help.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from printpilot.decision import decide
from printpilot.diagnosis import diagnose
from printpilot.domain import (
    ActionPlan,
    ActionType,
    DiagnosisResult,
    FaultCode,
    ParamName,
    SafetyDecision,
    SafetyVerdict,
)
from printpilot.execution import Executor
from printpilot.perception import perceive
from printpilot.safety import GateContext, review
from printpilot.simulator import (
    MATERIAL_SETPOINTS,
    Material,
    NoiseProfile,
    QualityReport,
    Telemetry,
    evaluate_quality,
    inject,
    sample,
)
from printpilot.simulator.fault_injection import PrintParams
from printpilot.simulator.scenario import Geometry, ScenarioFamily

#: Quality change smaller than this is noise, not an effect.
SIGNIFICANT_QUALITY_CHANGE = 0.02


class LoopOutcome(StrEnum):
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    HARMED = "harmed"
    BLOCKED = "blocked"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class LoopResult:
    case_id: str
    diagnosis: DiagnosisResult
    plan: ActionPlan
    verdict: SafetyVerdict
    before: QualityReport
    after: QualityReport | None
    outcome: LoopOutcome
    params_before: PrintParams
    params_after: PrintParams

    @property
    def delta(self) -> float:
        return 0.0 if self.after is None else self.after.score - self.before.score

    def summary(self) -> str:
        lines = [
            f"案例 {self.case_id}",
            f"  诊断    {self.diagnosis.top.fault_code.value}"
            f"（置信度 {self.diagnosis.top.confidence:.2f}）",
            f"  动作    {self.plan.action_type.value}",
            f"  门禁    {self.verdict.decision.value}",
        ]
        if self.verdict.violated_rules:
            lines += [f"          {rule}" for rule in self.verdict.violated_rules]
        lines.append(f"  质量    {self.before.score:.3f}")
        if self.after is not None:
            lines[-1] += f" → {self.after.score:.3f}（{self.delta:+.3f}）"
        lines.append(f"  结果    {self.outcome.value}")
        return "\n".join(lines)


def _simulate(
    family: ScenarioFamily,
    *,
    case_id: str,
    seed: str,
    layer_count: int,
    params: PrintParams,
) -> Telemetry:
    """Re-run the print. Same seed, so the only difference is the settings.

    Fault and noise draw from *derived* sub-seeds rather than two streams built on
    the same seed — identical streams would correlate the fault's parameters with
    the sensor noise. (``dataset.py`` avoids this by threading one RNG through
    both calls; here the two prints of a round must be seeded independently of
    each other's draw counts, so derivation is the equivalent.)
    """
    profile = inject(
        family.fault,
        layer_count=layer_count,
        material=family.material,
        rng=random.Random(f"{seed}:inject"),
        params=params,
    )
    return sample(
        profile,
        case_id=case_id,
        noise=family.noise,
        rng=random.Random(f"{seed}:sample"),
        setpoints=dict(MATERIAL_SETPOINTS[family.material]),
        dropped_signals=family.dropped_signals,
    )


def run_round(
    family: ScenarioFamily,
    *,
    case_id: str,
    seed: str,
    layer_count: int = 60,
    params: PrintParams | None = None,
) -> LoopResult:
    """Run one full round on a freshly simulated print."""
    before_params = params or PrintParams()
    telemetry = _simulate(
        family, case_id=case_id, seed=seed, layer_count=layer_count, params=before_params
    )
    report = perceive(telemetry, material=family.material.value)
    before = evaluate_quality(telemetry)

    diagnosis = diagnose(report)
    plan = decide(diagnosis, report)

    current = {
        ParamName.FLOW: before_params.flow_percent,
        ParamName.NOZZLE_TEMP: (
            MATERIAL_SETPOINTS[family.material]["nozzle_temp"] + before_params.nozzle_temp_offset
        ),
        ParamName.BED_TEMP: MATERIAL_SETPOINTS[family.material]["bed_temp"],
    }
    verdict = review(
        GateContext(
            plan=plan,
            diagnosis=diagnosis,
            report=report,
            current_params=current,
            material=family.material.value,
        )
    )

    if verdict.decision is not SafetyDecision.ALLOW:
        return LoopResult(
            case_id=case_id,
            diagnosis=diagnosis,
            plan=plan,
            verdict=verdict,
            before=before,
            after=None,
            outcome=LoopOutcome.BLOCKED,
            params_before=before_params,
            params_after=before_params,
        )

    if plan.action_type is not ActionType.APPLY_PARAM_PATCH:
        return LoopResult(
            case_id=case_id,
            diagnosis=diagnosis,
            plan=plan,
            verdict=verdict,
            before=before,
            after=None,
            outcome=LoopOutcome.NO_ACTION,
            params_before=before_params,
            params_after=before_params,
        )

    applied = Executor().apply(plan, verdict, current)
    after_params = PrintParams(
        flow_percent=applied.params[ParamName.FLOW],
        nozzle_temp_offset=applied.params[ParamName.NOZZLE_TEMP]
        - MATERIAL_SETPOINTS[family.material]["nozzle_temp"],
    )

    # Same seed: any difference in the second print comes from the settings, not
    # from a different roll of the noise.
    after_telemetry = _simulate(
        family, case_id=case_id, seed=seed, layer_count=layer_count, params=after_params
    )
    after = evaluate_quality(after_telemetry)

    change = after.score - before.score
    if change > SIGNIFICANT_QUALITY_CHANGE:
        outcome = LoopOutcome.IMPROVED
    elif change < -SIGNIFICANT_QUALITY_CHANGE:
        outcome = LoopOutcome.HARMED
    else:
        outcome = LoopOutcome.UNCHANGED

    return LoopResult(
        case_id=case_id,
        diagnosis=diagnosis,
        plan=plan,
        verdict=verdict,
        before=before,
        after=after,
        outcome=outcome,
        params_before=before_params,
        params_after=after_params,
    )


#: One family per injectable fault, so a demonstration exercises every path:
#: a patch that works, a patch refused by the interlock, and a deliberate no-op.
DEMO_FAULTS: tuple[FaultCode, ...] = (
    FaultCode.UNDEREXT_PARAM,
    FaultCode.THERMAL_DRIFT,
    FaultCode.CLOG_PARTIAL,
    FaultCode.CLOG_FULL,
    FaultCode.NORMAL_SUSPICIOUS,
)


def demo_families() -> list[ScenarioFamily]:
    return [
        ScenarioFamily(
            fault=fault,
            material=Material.PLA,
            geometry=Geometry.BOX,
            noise=NoiseProfile.NOMINAL,
        )
        for fault in DEMO_FAULTS
    ]
