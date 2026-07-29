"""Milestone bookkeeping.

`printpilot info` is the project's honesty mechanism: it reports completion from
code rather than from a hand-maintained README claim.
"""

from __future__ import annotations

from printpilot.status import MILESTONES, MilestoneStatus, completion_line, verified_count


def test_milestone_ids_are_unique_and_ordered() -> None:
    ids = [m.id for m in MILESTONES]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


def test_every_milestone_declares_an_acceptance_command() -> None:
    for milestone in MILESTONES:
        assert milestone.acceptance.strip(), f"{milestone.id} has no acceptance criterion"


def test_verified_count_matches_statuses() -> None:
    expected = sum(1 for m in MILESTONES if m.status is MilestoneStatus.VERIFIED)
    assert verified_count() == expected


def test_completion_line_reports_the_denominator() -> None:
    assert f"/{len(MILESTONES)}" in completion_line()


def test_status_markers_are_distinct() -> None:
    markers = {status.marker for status in MilestoneStatus}
    assert len(markers) == len(MilestoneStatus)
