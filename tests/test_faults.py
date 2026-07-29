"""Invariants over the fault catalogue.

These are the safety-critical facts the SafetyGate will rely on in M7. Asserting
them here means a careless edit to the catalogue fails the build rather than
quietly widening what the system is willing to do to a clogged nozzle.
"""

from __future__ import annotations

import pytest

from printpilot.domain import (
    FAULT_CATALOG,
    HARDWARE_BOUNDS,
    PARAM_UNITS,
    FaultCode,
    ParamName,
    RemediationClass,
    remediation_for,
)

CLOG_FAULTS = (FaultCode.CLOG_PARTIAL, FaultCode.CLOG_FULL)


def test_every_fault_code_has_a_spec() -> None:
    assert set(FAULT_CATALOG) == set(FaultCode)


@pytest.mark.parametrize("code", CLOG_FAULTS)
def test_clogs_are_never_parameter_fixable(code: FaultCode) -> None:
    """The v1 plan proposed compensating a clog with `flow +5`. It must not be
    reachable through the parameter path at all."""
    assert remediation_for(code) is not RemediationClass.PARAM_FIXABLE


@pytest.mark.parametrize("code", CLOG_FAULTS)
def test_clogs_forbid_increasing_flow(code: FaultCode) -> None:
    assert ParamName.FLOW in FAULT_CATALOG[code].forbidden_increase


def test_full_clog_requires_aborting() -> None:
    assert remediation_for(FaultCode.CLOG_FULL) is RemediationClass.ABORT


def test_param_fixable_faults_forbid_nothing() -> None:
    for code, spec in FAULT_CATALOG.items():
        if spec.remediation is RemediationClass.PARAM_FIXABLE:
            assert not spec.forbidden_increase, f"{code} is param-fixable but restricts params"


def test_normal_suspicious_means_no_action() -> None:
    """The false-positive trap: the correct response is to do nothing."""
    assert remediation_for(FaultCode.NORMAL_SUSPICIOUS) is RemediationClass.NO_ACTION


def test_unknown_is_undetermined_not_a_guess() -> None:
    assert remediation_for(FaultCode.UNKNOWN) is RemediationClass.UNDETERMINED


def test_every_fault_states_its_rationale() -> None:
    for code, spec in FAULT_CATALOG.items():
        assert spec.rationale.strip(), f"{code} has no rationale"


def test_every_param_has_a_unit_and_a_hardware_bound() -> None:
    assert set(PARAM_UNITS) == set(ParamName)
    assert set(HARDWARE_BOUNDS) == set(ParamName)


def test_hardware_bounds_are_self_consistent() -> None:
    for name, bound in HARDWARE_BOUNDS.items():
        assert bound.min_value < bound.max_value, f"{name} has an inverted range"
        assert bound.unit is PARAM_UNITS[name], f"{name} bound unit disagrees with PARAM_UNITS"
        span = bound.max_value - bound.min_value
        assert bound.max_abs_delta <= span, f"{name} allows a step larger than its whole range"
