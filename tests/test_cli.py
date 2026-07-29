"""CLI surface.

The unimplemented subcommands exit non-zero on purpose: a stub that returns 0
would make the milestone table look further along than the code is.
"""

from __future__ import annotations

import pytest

from printpilot import __version__
from printpilot.cli import EXIT_NOT_IMPLEMENTED, EXIT_OK, main


def test_info_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "当前完成度" in out
    assert "M1" in out


def test_info_states_the_boundary(capsys: pytest.CaptureFixture[str]) -> None:
    """README and CLI must both lead with the synthetic-data disclaimer."""
    main(["info"])
    out = capsys.readouterr().out
    assert "合成遥测" in out
    assert "不控制实机" in out


def test_bare_invocation_shows_info(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_OK
    assert "PrintPilot" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "milestone"),
    [
        (["dataset"], "M3"),
        (["eval", "--split", "dev"], "M4"),
        (["skills", "validate"], "M5"),
    ],
)
def test_unimplemented_commands_exit_nonzero(
    argv: list[str], milestone: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == EXIT_NOT_IMPLEMENTED
    assert milestone in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_rejects_unknown_command() -> None:
    with pytest.raises(SystemExit):
        main(["nope"])
