"""Shared fixtures.

Every fixture here is offline. No test in the core suite may require an API key.
"""

from __future__ import annotations

import pytest

from printpilot.domain import (
    EvidenceKind,
    EvidenceRef,
    FaultCode,
    Hypothesis,
    PhenomenonReport,
    SignalFeature,
)


@pytest.fixture
def flow_evidence() -> EvidenceRef:
    return EvidenceRef(
        kind=EvidenceKind.SIGNAL,
        ref="flow_ratio_series",
        detail="mean 0.71 over layers 25-60",
    )


@pytest.fixture
def clog_report() -> PhenomenonReport:
    """A partial-clog-looking case: flow down *and* extruder current up."""
    return PhenomenonReport(
        case_id="case-0001",
        scenario_family="clog_partial/pla/box",
        material="PLA",
        features=[
            SignalFeature(
                name="flow_ratio_mean", value=0.71, unit="ratio", threshold=0.85, exceeded=True
            ),
            SignalFeature(
                name="extruder_current_slope",
                value=0.042,
                unit="A_per_min",
                threshold=0.01,
                exceeded=True,
            ),
        ],
        available_signals=["flow_ratio_series", "extruder_current_series"],
        missing_signals=["humidity"],
    )


@pytest.fixture
def clog_hypothesis(flow_evidence: EvidenceRef) -> Hypothesis:
    return Hypothesis(
        fault_code=FaultCode.CLOG_PARTIAL,
        confidence=0.82,
        reasoning="流量比下降且挤出机电流上升，机械阻力升高。",
        evidence=[flow_evidence],
    )
