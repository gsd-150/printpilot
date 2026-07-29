"""Shared fixtures.

Every fixture here is offline. No test in the core suite may require an API key —
and, as of the guard below, none may reach a real endpoint even by accident.
"""

from __future__ import annotations

import pytest
from dotenv import load_dotenv as _real_load_dotenv

from printpilot.domain import (
    EvidenceKind,
    EvidenceRef,
    FaultCode,
    Hypothesis,
    PhenomenonReport,
    SignalFeature,
)

_LLM_ENV_VARS = (
    "OPENAI_API_KEY",
    "PRINTPILOT_LLM_BASE_URL",
    "PRINTPILOT_LLM_MODEL",
    "PRINTPILOT_LLM_BACKEND",
    "PRINTPILOT_LLM_STRUCTURED_MODE",
)


@pytest.fixture(autouse=True)
def isolate_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop any test from reaching a live endpoint.

    This exists because it already happened: once ``--diagnoser llm`` was wired
    up, a stale CLI test that expected it to be unimplemented instead ran the full
    dev split against the real API — 100 calls at roughly twenty seconds each,
    silently, inside `pytest`.

    Two measures, because either alone is leaky. The environment variables are
    cleared so nothing is configured; and auto-discovery of the developer's
    ``.env`` is disabled, since ``load_dotenv()`` with no argument walks up from
    the working directory and would put them straight back. Tests that need to
    exercise parsing pass an explicit path, which still works.
    """

    def only_explicit_paths(dotenv_path: object = None, **kwargs: object) -> bool:
        if dotenv_path is None:
            return False
        return bool(_real_load_dotenv(dotenv_path, **kwargs))  # type: ignore[arg-type]

    monkeypatch.setattr("printpilot.llm.config.load_dotenv", only_explicit_paths)
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


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
