"""Knowledge cards, cleaning, and the retrieval plumbing.

All offline. Retrieval *quality* cannot be tested here — the deterministic
embedder is not semantic, and a Hit@k produced by it would mean nothing. What is
tested is that the pipeline holds together: cards parse with provenance intact,
cleaning reports what it dropped, the store indexes and ranks, metadata filtering
narrows the result, and the metrics compute correctly on known inputs.

The measured retrieval numbers live in ``evals/results/retrieval.md`` and come
from a real embedder, the same arrangement as the LLM ablation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printpilot.rag import (
    CardParseError,
    DeterministicEmbedder,
    EvidenceLevel,
    KnowledgeCard,
    KnowledgeStore,
    RetrievalQuery,
    clean,
    evaluate,
    load_cards,
    load_queries,
    parse_card,
    similarity,
)
from printpilot.rag.retrieval_eval import QueryOutcome, RetrievalReport

CARD = """---
id: sample-card
title: 示例卡片
source_title: 本项目自撰
source_url: ""
license: CC-BY-4.0
retrieved_at: 2026-07-30
applicable_material: [PLA]
evidence_level: first_principles
tags: [sample]
---

挤出机电流上升说明推料阻力增大，这段正文足够长以通过清洗流水线的长度检查，
因此不会被剔除，可以用来验证解析与索引。
"""


def _card(card_id: str, body: str) -> KnowledgeCard:
    return parse_card(CARD.replace("id: sample-card", f"id: {card_id}"), card_id).model_copy(
        update={"body": body}
    )


class TestCardParsing:
    def test_reads_frontmatter_and_body(self) -> None:
        card = parse_card(CARD, "sample")
        assert card.id == "sample-card"
        assert card.evidence_level is EvidenceLevel.FIRST_PRINCIPLES
        assert card.applicable_material == ("PLA",)

    def test_an_unquoted_date_survives(self) -> None:
        """YAML resolves `2026-07-30` to a date object. Same class of leak as a
        bare `1.0` becoming a float in a Skill version."""
        assert parse_card(CARD, "s").retrieved_at == "2026-07-30"

    def test_content_hash_changes_with_the_text(self) -> None:
        """So a silent edit to a cited passage is detectable downstream."""
        assert _card("a", "原文").content_hash != _card("a", "改过的原文").content_hash

    def test_missing_frontmatter(self) -> None:
        with pytest.raises(CardParseError, match="no frontmatter"):
            parse_card("just a body", "s")

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(CardParseError, match="does not match"):
            parse_card(CARD.replace("tags: [sample]", "tags: [sample]\ninvented: 1"), "s")


class TestShippedCorpus:
    @pytest.fixture(scope="class")
    def cards(self) -> list[KnowledgeCard]:
        return load_cards()

    def test_the_corpus_loads(self, cards: list[KnowledgeCard]) -> None:
        assert len(cards) >= 10

    def test_every_card_carries_provenance(self, cards: list[KnowledgeCard]) -> None:
        """A passage with no provenance cannot be audited, superseded, or weighed
        against a conflicting one."""
        for card in cards:
            assert card.source_title
            assert card.license
            assert card.retrieved_at

    def test_ids_are_unique(self, cards: list[KnowledgeCard]) -> None:
        assert len({c.id for c in cards}) == len(cards)

    def test_no_fabricated_source_urls(self, cards: list[KnowledgeCard]) -> None:
        """These cards are authored, not transcribed. An empty URL is honest; a
        plausible-looking one would be an invented citation."""
        for card in cards:
            assert card.source_url == "", f"{card.id} claims a source URL"

    def test_every_query_in_the_eval_set_names_a_real_card(
        self, cards: list[KnowledgeCard]
    ) -> None:
        known = {c.id for c in cards}
        for query in load_queries():
            missing = set(query.relevant) - known
            assert not missing, f"{query.qid} expects cards that do not exist: {missing}"

    def test_every_card_is_covered_by_at_least_one_query(self, cards: list[KnowledgeCard]) -> None:
        """An unqueried card is untested corpus."""
        covered = {card_id for q in load_queries() for card_id in q.relevant}
        assert {c.id for c in cards} <= covered


class TestCleaning:
    def test_reports_counts_in_and_out(self) -> None:
        """A cleaning step that reports nothing has not been shown to do anything."""
        report = clean([_card("a", "甲" * 200), _card("b", "乙" * 200)])
        assert (report.total_in, report.total_out) == (2, 2)
        assert "2 进 → 2 出" in report.format()

    def test_drops_a_too_short_card(self) -> None:
        report = clean([_card("a", "太短")])
        assert report.total_out == 0
        assert "正文不足" in report.format()

    def test_drops_a_near_duplicate(self) -> None:
        body = (
            "机械通路变窄时，推送同样多的料需要更大的力，因此电流随流量下降而上升。"
            "而 flow 设定偏低只是少推料，通路并未改变，阻力不变。"
            "两者因此耦合方向相反，符号差异比绝对阈值稳健。"
        )
        report = clean([_card("a", body), _card("b", body + "另有一句补充说明。")])
        assert report.total_out == 1
        assert any("近重复" in reason for _, reason in report.dropped)

    def test_drops_a_superseded_card(self) -> None:
        old = _card("old", "甲" * 200)
        new = _card("new", "乙" * 200).model_copy(update={"supersedes": "old"})
        report = clean([old, new])
        assert [c.id for c in report.kept] == ["new"]

    def test_similarity_is_symmetric_and_bounded(self) -> None:
        assert similarity("abcdef", "abcdef") == pytest.approx(1.0)
        assert similarity("abcdef", "zyxwvu") == pytest.approx(0.0)
        assert similarity("abcdef", "abcxyz") == similarity("abcxyz", "abcdef")


class TestStore:
    @pytest.fixture(scope="class")
    def store(self) -> KnowledgeStore:
        store = KnowledgeStore(embedder=DeterministicEmbedder())
        store.build(load_cards())
        return store

    def test_indexes_the_whole_corpus(self, store: KnowledgeStore) -> None:
        assert store.size == len(load_cards())

    def test_returns_the_requested_number(self, store: KnowledgeStore) -> None:
        assert len(store.query("挤出机电流", top_k=3)) == 3

    def test_results_carry_a_citable_source(self, store: KnowledgeStore) -> None:
        assert all(r.source_label for r in store.query("堵塞", top_k=3))

    def test_material_filter_narrows_the_result(self) -> None:
        """Filtering before ranking, so top_k returns applicable cards rather than
        candidates that are then discarded."""
        store = KnowledgeStore(embedder=DeterministicEmbedder())
        store.build(load_cards())
        petg = store.query("温度窗口", top_k=5, material="PETG")
        assert all("PETG" in r.metadata["applicable_material"] for r in petg)

    def test_querying_before_building_is_an_error(self) -> None:
        with pytest.raises(RuntimeError, match="not been built"):
            KnowledgeStore(embedder=DeterministicEmbedder()).query("x")

    def test_scores_are_similarities_not_distances(self, store: KnowledgeStore) -> None:
        results = store.query("挤出机电流上升", top_k=3)
        assert results == sorted(results, key=lambda r: -r.score)


class TestRetrievalMetrics:
    def _outcome(self, retrieved: list[str], relevant: list[str]) -> QueryOutcome:
        return QueryOutcome(qid="q", retrieved=tuple(retrieved), relevant=frozenset(relevant))

    def test_hit_at_k_respects_the_window(self) -> None:
        outcome = self._outcome(["a", "b", "c"], ["c"])
        assert not outcome.hit_at(1)
        assert not outcome.hit_at(2)
        assert outcome.hit_at(3)

    def test_reciprocal_rank_rewards_position(self) -> None:
        assert self._outcome(["a", "b"], ["a"]).reciprocal_rank == pytest.approx(1.0)
        assert self._outcome(["a", "b"], ["b"]).reciprocal_rank == pytest.approx(0.5)
        assert self._outcome(["a", "b"], ["z"]).reciprocal_rank == pytest.approx(0.0)

    def test_mrr_separates_first_from_merely_present(self) -> None:
        """Hit@3 cannot tell these apart; MRR is why both are reported."""
        first = RetrievalReport(
            embedder="t",
            semantic=True,
            corpus_size=3,
            outcomes=(self._outcome(["a", "b", "c"], ["a"]),),
        )
        third = RetrievalReport(
            embedder="t",
            semantic=True,
            corpus_size=3,
            outcomes=(self._outcome(["b", "c", "a"], ["a"]),),
        )
        assert first.hit_rate(3) == third.hit_rate(3) == 1.0
        assert first.mrr > third.mrr

    def test_a_non_semantic_embedder_is_flagged_in_the_report(self) -> None:
        """So a number produced by the stand-in cannot be quoted as a result."""
        store = KnowledgeStore(embedder=DeterministicEmbedder())
        store.build(load_cards())
        report = evaluate(store, load_queries()[:3])
        assert not report.semantic
        assert "不可对外引用" in report.format()

    def test_query_set_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "qa.jsonl"
        path.write_text('{"qid":"q1","query":"x","relevant":["a"]}\n', encoding="utf-8")
        assert load_queries(path) == [RetrievalQuery(qid="q1", query="x", relevant=("a",))]
