"""Dataset persistence.

The separation of ``cases.jsonl`` from ``labels.jsonl`` is the point of these
tests. Ground truth being in a different file, reached by a different function,
means leaking it into an agent prompt takes a deliberate act rather than a
forgotten ``del``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from printpilot.simulator import (
    CaseInput,
    Split,
    load_cases,
    load_labels,
    write_dataset,
)


@pytest.fixture(scope="module")
def dataset_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("datasets")
    write_dataset(root, master_seed=42)
    return root


class TestLabelSeparation:
    def test_cases_file_contains_no_fault_information(self, dataset_root: Path) -> None:
        raw = (dataset_root / "dev" / "cases.jsonl").read_text(encoding="utf-8")
        for leaked in ("fault_code", "remediation", "onset_layer", "residual_flow"):
            assert leaked not in raw, f"{leaked} must not appear in the agent-visible file"

    def test_case_schema_has_no_answer_fields(self) -> None:
        forbidden = {"fault_codes", "remediation", "baseline_quality", "onset_layer"}
        assert not forbidden & set(CaseInput.model_fields)

    def test_family_id_does_not_spell_out_the_fault_to_readers_of_cases_only(
        self, dataset_root: Path
    ) -> None:
        """Known limitation, asserted so it stays visible: family_id embeds the fault
        code, so an evaluation harness must not put it in the prompt. Perception is
        given telemetry, never the case metadata."""
        cases = load_cases(dataset_root, Split.DEV)
        assert any(c.family_id.startswith("CLOG_PARTIAL") for c in cases)


class TestRoundTrip:
    def test_counts_match_the_plan(self, dataset_root: Path) -> None:
        assert len(load_cases(dataset_root, Split.DEV)) == 100
        assert len(load_cases(dataset_root, Split.HOLDOUT)) == 30
        assert len(load_cases(dataset_root, Split.CHALLENGE)) == 30

    def test_cases_and_labels_align(self, dataset_root: Path) -> None:
        for split in Split:
            cases = load_cases(dataset_root, split)
            labels = load_labels(dataset_root, split)
            assert [c.case_id for c in cases] == [label.case_id for label in labels]

    def test_case_ids_are_unique(self, dataset_root: Path) -> None:
        ids = [c.case_id for split in Split for c in load_cases(dataset_root, split)]
        assert len(ids) == len(set(ids)) == 160

    def test_telemetry_survives_serialisation(self, dataset_root: Path) -> None:
        case = load_cases(dataset_root, Split.DEV)[0]
        assert case.telemetry.layer_count == len(case.telemetry.signals["flow_ratio"])

    def test_blinded_challenge_cases_really_lack_the_signal(self, dataset_root: Path) -> None:
        blinded = [
            c
            for c in load_cases(dataset_root, Split.CHALLENGE)
            if "extruder_current" in c.telemetry.missing_signals
        ]
        assert len(blinded) == 10
        assert all("extruder_current" not in c.telemetry.signals for c in blinded)


class TestManifest:
    def _manifest(self, root: Path) -> dict[str, object]:
        loaded: dict[str, object] = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        return loaded

    def test_records_what_is_needed_to_reproduce(self, dataset_root: Path) -> None:
        manifest = self._manifest(dataset_root)
        for key in ("master_seed", "scenario_version", "generator", "digests", "families"):
            assert key in manifest

    def test_declares_the_data_as_synthetic(self, dataset_root: Path) -> None:
        manifest = self._manifest(dataset_root)
        assert manifest["synthetic"] is True
        assert "virtual sensors" in str(manifest["notice"])

    def test_digests_are_stable_for_a_seed(self, dataset_root: Path, tmp_path: Path) -> None:
        again = write_dataset(tmp_path / "again", master_seed=42)
        assert again["digests"] == self._manifest(dataset_root)["digests"]

    def test_digests_change_with_the_seed(self, tmp_path: Path) -> None:
        a = write_dataset(tmp_path / "a", master_seed=1)
        b = write_dataset(tmp_path / "b", master_seed=2)
        assert a["digests"] != b["digests"]

    def test_fault_distribution_is_balanced_in_dev(self, dataset_root: Path) -> None:
        distribution = self._manifest(dataset_root)["fault_distribution"]
        assert isinstance(distribution, dict)
        assert set(distribution["dev"].values()) == {20}
