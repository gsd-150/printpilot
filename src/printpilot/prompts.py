"""Versioned prompt loading.

Prompts are **files, not string constants**. The path is the version, the
frontmatter records what a revision was trying to fix, and ``CHANGELOG.md``
records whether it worked. A prompt buried in a Python string cannot be diffed
against the eval report that justified it.

Frontmatter is intentionally flat ``key: value`` lines — no nested structures, no
YAML dependency, nothing to get clever about.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"

_DELIMITER = "---"


class PromptError(RuntimeError):
    """A prompt file is missing or malformed."""


@dataclass(frozen=True)
class Prompt:
    name: str
    metadata: dict[str, str]
    template: str

    @property
    def version(self) -> str:
        return self.metadata.get("version", "?")

    def render(self, **values: str) -> str:
        try:
            return self.template.format(**values)
        except KeyError as exc:
            msg = f"prompt {self.name!r} needs placeholder {exc} which was not supplied"
            raise PromptError(msg) from exc


def parse_prompt(name: str, text: str) -> Prompt:
    if not text.startswith(_DELIMITER):
        msg = f"prompt {name!r} has no frontmatter block"
        raise PromptError(msg)

    _, front, body = text.split(_DELIMITER, 2)
    metadata: dict[str, str] = {}
    for line in front.strip().splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    if "version" not in metadata:
        msg = f"prompt {name!r} does not declare a version"
        raise PromptError(msg)

    return Prompt(name=name, metadata=metadata, template=body.strip())


def load_prompt(relative: str, root: Path | None = None) -> Prompt:
    """Load e.g. ``"diagnosis/v1_baseline"``."""
    base = root or PROMPTS_ROOT
    path = base / f"{relative}.md"
    if not path.exists():
        msg = f"no prompt at {path}"
        raise PromptError(msg)
    return parse_prompt(relative, path.read_text(encoding="utf-8"))
