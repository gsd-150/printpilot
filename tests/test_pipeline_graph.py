"""The assembled pipeline: the real five-node graph, not the smoke miniature.

What ``test_langgraph_smoke.py`` proved about the framework, this suite proves
about the pipeline itself — above all that the conditional edge is
load-bearing: a round whose plan the gate refuses, or that has nothing to
execute, ends without the execute node ever running.
"""

from __future__ import annotations

import random

import pytest

from printpilot.domain import ActionType, FaultCode, ParamName, SafetyDecision
from printpilot.loop import run_round
from printpilot.simulator import (
    MATERIAL_SETPOINTS,
    Material,
    NoiseProfile,
    ScenarioFamily,
    Telemetry,
    inject,
    sample,
)
from printpilot.simulator.scenario import Geometry
from printpilot.workflow import NodeContractError, PipelineState, build_pipeline, run_pipeline
from printpilot.workflow.graph import default_pipeline


def _telemetry(fault: FaultCode) -> Telemetry:
    profile = inject(fault, layer_count=60, material=Material.PLA, rng=random.Random("g"))
    return sample(
        profile,
        case_id="g",
        noise=NoiseProfile.NOMINAL,
        rng=random.Random("g"),
        setpoints=dict(MATERIAL_SETPOINTS[Material.PLA]),
    )


def _state(fault: FaultCode) -> PipelineState:
    setpoints = MATERIAL_SETPOINTS[Material.PLA]
    return PipelineState(
        case_id="g",
        material=Material.PLA.value,
        current_params={
            ParamName.FLOW: 100.0,
            ParamName.NOZZLE_TEMP: setpoints["nozzle_temp"],
            ParamName.BED_TEMP: setpoints["bed_temp"],
        },
        telemetry=_telemetry(fault),
    )


class TestRouting:
    def test_a_parameter_fault_reaches_the_execute_node(self) -> None:
        final = run_pipeline(_state(FaultCode.UNDEREXT_PARAM))
        assert final.verdict is not None
        assert final.verdict.decision is SafetyDecision.ALLOW
        assert final.execution is not None and final.execution.applied
        assert final.execution.params[ParamName.FLOW] == 105.0

    @pytest.mark.parametrize("fault", [FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL])
    def test_a_clog_round_ends_without_executing(self, fault: FaultCode) -> None:
        final = run_pipeline(_state(fault))
        assert final.plan is not None
        assert final.plan.action_type is not ActionType.APPLY_PARAM_PATCH
        assert final.execution is None, "the conditional edge must route a clog past execution"

    def test_every_stage_output_lands_on_the_state(self) -> None:
        """The state doubles as the round's record: each node's output is
        there, or explicitly None because routing ended the round early."""
        final = run_pipeline(_state(FaultCode.NORMAL_SUSPICIOUS))
        assert final.report is not None
        assert final.diagnosis is not None
        assert final.plan is not None
        assert final.verdict is not None


class TestLoopIntegration:
    def test_the_loop_and_an_explicit_graph_agree(self) -> None:
        """`run_round` without a pipeline uses the same graph it would be
        handed explicitly — byte-for-byte identical results."""
        family = ScenarioFamily(
            fault=FaultCode.UNDEREXT_PARAM,
            material=Material.PLA,
            geometry=Geometry.BOX,
            noise=NoiseProfile.NOMINAL,
        )
        default = run_round(family, case_id="c", seed="fixed")
        explicit = run_round(family, case_id="c", seed="fixed", pipeline=build_pipeline())
        assert default == explicit

    def test_the_default_pipeline_is_compiled_once(self) -> None:
        assert default_pipeline() is default_pipeline()


class TestNodeContract:
    def test_a_decider_returning_the_wrong_type_is_caught(self) -> None:
        """The M2 wrapper does its production job: a node writing a string
        into the `plan` channel is a NodeContractError, not a latent state."""
        graph = build_pipeline(decider=lambda diagnosis, report: "nonsense")  # type: ignore[arg-type, return-value]
        with pytest.raises(NodeContractError, match="_decide"):
            run_pipeline(_state(FaultCode.UNDEREXT_PARAM), graph=graph)
