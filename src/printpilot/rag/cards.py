"""Knowledge cards: the corpus, and what each chunk must carry with it.

Every chunk records where it came from, under what licence, and how strong the
claim is. A retrieved passage with no provenance cannot be audited, cannot be
superseded, and cannot be weighed against a conflicting one — which makes the
priority chain in ``knowledge-conflict-priority`` unenforceable.

**Honesty about the corpus**: these cards are written for this project from general
FDM process knowledge. They are not transcriptions of any particular document, and
``source_url`` is deliberately empty rather than filled with a plausible-looking
link. A production system would need sourced material with real citations; that is
recorded as a limitation, not disguised.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"
ACCEPTED = "accepted"
CANDIDATE = "candidate_cases"

#: Prefix for the per-material boolean metadata keys used for filtering.
MATERIAL_PREFIX = "material_"

_DELIMITER = "---"


class EvidenceLevel(StrEnum):
    """How much weight a claim carries, from strongest to weakest."""

    MANUFACTURER = "manufacturer_documentation"
    COMMUNITY = "community_practice"
    FIRST_PRINCIPLES = "first_principles"
    CASE_HISTORY = "case_history"


class CardParseError(RuntimeError):
    """A knowledge card could not be read."""


class KnowledgeCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    source_title: str
    source_url: str = ""
    license: str
    retrieved_at: str
    applicable_material: tuple[str, ...] = ()
    evidence_level: EvidenceLevel
    supersedes: str | None = None
    tags: tuple[str, ...] = ()

    @field_validator("retrieved_at", mode="before")
    @classmethod
    def _dates_are_strings(cls, value: object) -> object:
        """YAML resolves an unquoted ``2026-07-30`` to ``datetime.date``.

        The same class of leak as a bare ``1.0`` becoming a float in a Skill's
        version field: the file looks like text, the parser disagrees. Normalising
        here beats requiring every author to remember the quotes.
        """
        return value.isoformat() if isinstance(value, date) else value

    @property
    def content_hash(self) -> str:
        """Identifies the text, so a silent edit is detectable downstream."""
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()[:16]

    def as_document(self) -> str:
        """What is embedded and what the model reads. Title included: it carries
        real signal and is short."""
        return f"{self.title}\n\n{self.body}"

    def metadata(self) -> dict[str, str | bool]:
        """Flat scalars, because that is all a vector store's metadata accepts.

        Materials become one boolean key each rather than a joined string. The
        joined form was the first attempt and silently broke filtering: a store's
        ``$in`` means "the field equals one of these", not "this appears inside the
        field", so a query for PLA matched nothing at all — every card listed
        several materials. The test that should have caught it asserted a property
        over the results and passed vacuously on the empty list.
        """
        return {
            "id": self.id,
            "title": self.title,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "license": self.license,
            "retrieved_at": self.retrieved_at,
            "evidence_level": self.evidence_level.value,
            "applicable_material": ",".join(self.applicable_material),
            **{f"{MATERIAL_PREFIX}{m}": True for m in self.applicable_material},
            "tags": ",".join(self.tags),
            "content_hash": self.content_hash,
            "supersedes": self.supersedes or "",
        }


def parse_card(text: str, source: str) -> KnowledgeCard:
    if not text.startswith(_DELIMITER):
        msg = f"{source}: no frontmatter block"
        raise CardParseError(msg)

    _, front, body = text.split(_DELIMITER, 2)
    try:
        loaded: Any = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        msg = f"{source}: frontmatter is not valid YAML: {exc}"
        raise CardParseError(msg) from exc

    if not isinstance(loaded, dict):
        msg = f"{source}: frontmatter must be a mapping"
        raise CardParseError(msg)

    try:
        return KnowledgeCard.model_validate({**loaded, "body": body.strip()})
    except ValidationError as exc:
        msg = f"{source}: does not match the card schema: {exc}"
        raise CardParseError(msg) from exc


def load_cards(root: Path | None = None, folder: str = ACCEPTED) -> list[KnowledgeCard]:
    """Load a corpus folder, sorted by id for stable ordering."""
    base = (root or KNOWLEDGE_ROOT) / folder
    if not base.exists():
        return []
    cards = [
        parse_card(path.read_text(encoding="utf-8"), source=path.name)
        for path in sorted(base.glob("*.md"))
    ]
    return sorted(cards, key=lambda c: c.id)
