"""The README's completion claim must match what the code reports.

`printpilot info` reads the milestone table from code so the stated progress
cannot drift ahead of the implementation. That only works if the README quotes the
same number — and it did drift: the README claimed 7/8 while the runtime reported
5/8, because the figure was hand-edited.
"""

from __future__ import annotations

import re
from pathlib import Path

from printpilot.status import MILESTONES, verified_count

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_quotes_the_runtime_completion_count() -> None:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+)\s*/\s*(\d+)\s*里程碑已验证\*\*", text)
    assert match, "README must state completion as **N / M 里程碑已验证**"
    assert (int(match.group(1)), int(match.group(2))) == (verified_count(), len(MILESTONES))


def test_the_milestone_table_marks_the_same_ones_verified() -> None:
    text = README.read_text(encoding="utf-8")
    ticked = {
        m.group(1) for m in re.finditer(r"^\|\s*✅\s*\|\s*\*\*(M\d)\*\*", text, flags=re.MULTILINE)
    }
    from printpilot.status import MilestoneStatus

    expected = {m.id for m in MILESTONES if m.status is MilestoneStatus.VERIFIED}
    assert ticked == expected
