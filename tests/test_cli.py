"""CLI surface.

The unimplemented subcommands exit non-zero on purpose: a stub that returns 0
would make the milestone table look further along than the code is.
"""

from __future__ import annotations

from pathlib import Path

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


def test_dataset_command_generates_a_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["dataset", "--out", str(tmp_path), "--seed", "7"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "160" in out
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "dev" / "cases.jsonl").exists()
    assert (tmp_path / "dev" / "labels.jsonl").exists()


def test_dataset_command_warns_about_label_separation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["dataset", "--out", str(tmp_path)])
    assert "标签不应进入 Agent 上下文" in capsys.readouterr().out


def test_eval_runs_the_rules_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["dataset", "--out", str(tmp_path)])
    capsys.readouterr()

    assert main(["eval", "--split", "holdout", "--data", str(tmp_path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "准确率" in out
    assert "堵塞误入参数路径" in out


def test_eval_without_a_dataset_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval", "--data", str(tmp_path)]) == EXIT_NOT_IMPLEMENTED
    assert "printpilot dataset" in capsys.readouterr().err


def test_eval_rejects_an_unimplemented_diagnoser(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["dataset", "--out", str(tmp_path)])
    capsys.readouterr()
    assert main(["eval", "--data", str(tmp_path), "--diagnoser", "llm+rag"]) == EXIT_NOT_IMPLEMENTED
    assert "尚未实现" in capsys.readouterr().err


def test_eval_with_llm_refuses_when_unconfigured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `isolate_llm_environment` guard makes this the only reachable outcome
    inside the suite, which is the point: no test can spend tokens."""
    main(["dataset", "--out", str(tmp_path)])
    capsys.readouterr()
    assert main(["eval", "--data", str(tmp_path), "--diagnoser", "llm"]) == EXIT_NOT_IMPLEMENTED
    assert "LLM 未配置" in capsys.readouterr().err


def test_skills_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["skills", "list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "extrusion-anomaly-triage" in out
    assert "safe-action-selection" in out


def test_skills_validate_passes_on_the_shipped_skills(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["skills", "validate"]) == EXIT_OK
    assert "全部通过校验" in capsys.readouterr().out


def test_skills_validate_fails_on_deliberately_broken_skills(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The check that the check works. A validate command that cannot fail is
    decoration, so CI runs it against fixtures built to break each rule."""
    root = Path(__file__).parent / "fixtures" / "bad_skills"
    assert main(["skills", "validate", "--root", str(root)]) == EXIT_NOT_IMPLEMENTED
    err = capsys.readouterr().err
    for rule in ("R0", "R1", "R2", "R3", "R5"):
        assert rule in err, f"{rule} did not fire on the fixtures"


def test_skills_route_needs_a_case(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["skills", "route"]) == EXIT_NOT_IMPLEMENTED
    assert "--case" in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_rejects_unknown_command() -> None:
    with pytest.raises(SystemExit):
        main(["nope"])
