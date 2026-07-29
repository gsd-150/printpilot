"""Dataset generation.

Inputs and labels are written to **separate files**. Leaking the answer into the
agent's context then requires opening a different file on purpose, rather than
forgetting to strip a field — the plan review (P0-5) asked that ground truth not
be reachable at evaluation time, and separating the artefacts is the cheapest way
to make that structural instead of procedural.

Generation is fully determined by ``master_seed``. Each case seeds its own RNG from
``f"{master_seed}:{case_id}"``, so a case reproduces identically no matter what
order the dataset is generated in or how many cases precede it.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from printpilot import __version__
from printpilot.domain import FaultCode, RemediationClass, remediation_for
from printpilot.simulator.fault_injection import inject
from printpilot.simulator.quality_evaluator import evaluate_quality
from printpilot.simulator.scenario import (
    MATERIAL_SETPOINTS,
    SCENARIO_VERSION,
    Geometry,
    Material,
    NoiseProfile,
    ScenarioFamily,
    Split,
    build_split_plan,
)
from printpilot.simulator.virtual_sensors import Telemetry, sample

DATASET_SCHEMA_VERSION: Final = "1.0.0"
DEFAULT_MASTER_SEED: Final = 42
MIN_LAYERS: Final = 40
MAX_LAYERS: Final = 80


class CaseInput(BaseModel):
    """What the pipeline is allowed to see."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    split: Split
    material: Material
    geometry: Geometry
    noise: NoiseProfile
    telemetry: Telemetry


class CaseLabel(BaseModel):
    """Ground truth. Never passed to a diagnosis or decision node."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    # A list even though the current generator injects one fault per case: the
    # metrics are multi-label from the start so adding combinations later does not
    # require reshaping every stored label.
    fault_codes: list[FaultCode] = Field(min_length=1)
    remediation: RemediationClass
    onset_layer: int | None = None
    residual_flow: float | None = None
    baseline_quality: float = Field(ge=0.0, le=1.0)


def _build_case(
    family: ScenarioFamily, case_id: str, master_seed: int
) -> tuple[CaseInput, CaseLabel]:
    rng = random.Random(f"{master_seed}:{case_id}")
    layer_count = rng.randint(MIN_LAYERS, MAX_LAYERS)

    profile = inject(family.fault, layer_count=layer_count, material=family.material, rng=rng)
    telemetry = sample(
        profile,
        case_id=case_id,
        noise=family.noise,
        rng=rng,
        setpoints=dict(MATERIAL_SETPOINTS[family.material]),
        dropped_signals=family.dropped_signals,
    )

    case = CaseInput(
        case_id=case_id,
        family_id=family.family_id,
        split=_split_of(case_id),
        material=family.material,
        geometry=family.geometry,
        noise=family.noise,
        telemetry=telemetry,
    )
    label = CaseLabel(
        case_id=case_id,
        family_id=family.family_id,
        fault_codes=[family.fault],
        remediation=remediation_for(family.fault),
        onset_layer=profile.onset_layer,
        residual_flow=profile.residual_flow,
        baseline_quality=evaluate_quality(telemetry).score,
    )
    return case, label


def _split_of(case_id: str) -> Split:
    return Split(case_id.split("-", 1)[0])


def generate(
    master_seed: int = DEFAULT_MASTER_SEED,
) -> dict[Split, list[tuple[CaseInput, CaseLabel]]]:
    """Materialise every case described by the split plan."""
    out: dict[Split, list[tuple[CaseInput, CaseLabel]]] = {}
    for split, plans in build_split_plan().items():
        rows: list[tuple[CaseInput, CaseLabel]] = []
        for plan in plans:
            for _ in range(plan.cases):
                case_id = f"{split.value}-{len(rows):04d}"
                rows.append(_build_case(plan.family, case_id, master_seed))
        out[split] = rows
    return out


def _write_jsonl(path: Path, rows: list[BaseModel]) -> str:
    """Write one JSON object per line; return the sha256 of the bytes written."""
    payload = "".join(row.model_dump_json() + "\n" for row in rows).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def write_dataset(root: Path, master_seed: int = DEFAULT_MASTER_SEED) -> dict[str, object]:
    """Generate and persist the dataset. Returns the manifest."""
    generated = generate(master_seed)
    digests: dict[str, dict[str, str]] = {}
    counts: dict[str, int] = {}
    fault_distribution: dict[str, dict[str, int]] = {}
    families: dict[str, list[str]] = {}

    for split, rows in generated.items():
        cases = [c for c, _ in rows]
        labels = [label for _, label in rows]
        digests[split.value] = {
            "cases_sha256": _write_jsonl(root / split.value / "cases.jsonl", list(cases)),
            "labels_sha256": _write_jsonl(root / split.value / "labels.jsonl", list(labels)),
        }
        counts[split.value] = len(rows)
        families[split.value] = sorted({c.family_id for c in cases})
        distribution: dict[str, int] = {}
        for label in labels:
            for code in label.fault_codes:
                distribution[code.value] = distribution.get(code.value, 0) + 1
        fault_distribution[split.value] = dict(sorted(distribution.items()))

    manifest: dict[str, object] = {
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "scenario_version": SCENARIO_VERSION,
        "generator": f"printpilot {__version__}",
        "master_seed": master_seed,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "synthetic": True,
        "notice": (
            "All telemetry is synthetic and produced by printpilot.simulator. "
            "flow_ratio and extruder_current are virtual sensors without a direct "
            "equivalent on stock consumer FDM hardware."
        ),
        "counts": counts,
        "fault_distribution": fault_distribution,
        "families": families,
        "digests": digests,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def load_cases(root: Path, split: Split) -> list[CaseInput]:
    path = root / split.value / "cases.jsonl"
    with path.open(encoding="utf-8") as handle:
        return [CaseInput.model_validate_json(line) for line in handle if line.strip()]


def load_labels(root: Path, split: Split) -> list[CaseLabel]:
    """Deliberately a separate call from :func:`load_cases`.

    Evaluation code has to ask for the answers explicitly; nothing that builds an
    agent prompt has a reason to call this.
    """
    path = root / split.value / "labels.jsonl"
    with path.open(encoding="utf-8") as handle:
        return [CaseLabel.model_validate_json(line) for line in handle if line.strip()]
