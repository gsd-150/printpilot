"""Discover and parse ``SKILL.md`` files.

Loading is separate from validation on purpose: ``skills validate`` needs to report
on a malformed Skill, which means it has to load far enough to name it. A parse
failure therefore raises with the path attached rather than being swallowed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from printpilot.skills_runtime.schema import Skill, SkillMeta

SKILL_FILENAME = "SKILL.md"
SKILLS_ROOT = Path(__file__).resolve().parents[3] / "skills"

_DELIMITER = "---"


class SkillParseError(RuntimeError):
    """A ``SKILL.md`` could not be read as a Skill."""


def parse_skill(text: str, source: str) -> Skill:
    if not text.startswith(_DELIMITER):
        msg = f"{source}: no frontmatter block"
        raise SkillParseError(msg)

    _, front, body = text.split(_DELIMITER, 2)
    try:
        loaded: Any = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        msg = f"{source}: frontmatter is not valid YAML: {exc}"
        raise SkillParseError(msg) from exc

    if not isinstance(loaded, dict):
        msg = f"{source}: frontmatter must be a mapping, got {type(loaded).__name__}"
        raise SkillParseError(msg)

    try:
        meta = SkillMeta.model_validate(loaded)
    except ValidationError as exc:
        msg = f"{source}: frontmatter does not match the Skill schema: {exc}"
        raise SkillParseError(msg) from exc

    stripped = body.strip()
    if not stripped:
        msg = f"{source}: body is empty"
        raise SkillParseError(msg)

    return Skill(meta=meta, body=stripped, source=source)


def scan(root: Path | None = None) -> list[Skill]:
    """Load every Skill under ``root``, sorted by name for stable output.

    Raises on the first malformed file. Use :func:`scan_tolerant` where the caller
    needs to report on bad Skills rather than be stopped by them.
    """
    skills, failures = scan_tolerant(root)
    if failures:
        source, error = failures[0]
        msg = f"{source}: {error}"
        raise SkillParseError(msg)
    return skills


def scan_tolerant(root: Path | None = None) -> tuple[list[Skill], list[tuple[str, str]]]:
    """Load what parses; return the rest as ``(source, error)`` pairs.

    A validation tool that dies on the first malformed input is not a validation
    tool — it reports one problem per run and hides the others behind it.
    """
    base = root or SKILLS_ROOT
    if not base.exists():
        return [], []

    skills: list[Skill] = []
    failures: list[tuple[str, str]] = []
    for path in sorted(base.rglob(SKILL_FILENAME)):
        source = str(path.relative_to(base))
        try:
            skills.append(parse_skill(path.read_text(encoding="utf-8"), source=source))
        except SkillParseError as exc:
            failures.append((source, str(exc)))
    return sorted(skills, key=lambda s: s.name), failures
