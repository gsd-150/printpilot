"""ChromaDB-backed retrieval.

An honest note on the choice: at twelve cards a brute-force cosine scan over a
list would return identical results in less time than Chroma takes to start. The
vector database is not here for approximate-nearest-neighbour speed at this size.

It is here for the interface — persistence, metadata filtering, and a query path
that does not change shape when the corpus grows past the point where the naive
scan stops being reasonable. Retrieval quality at this scale is a property of the
embedding and the corpus, not of the index, and the numbers this produces should
be read that way.

Embeddings are supplied by us rather than by Chroma's built-in function, so the
backend and the embedding model are independent choices and either can be swapped
without touching the other.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from printpilot.rag.cards import MATERIAL_PREFIX, KnowledgeCard
from printpilot.rag.embedding import Embedder

COLLECTION = "printpilot-knowledge"


@dataclass(frozen=True)
class Retrieved:
    card_id: str
    title: str
    body: str
    score: float
    metadata: dict[str, str]

    @property
    def source_label(self) -> str:
        """What a citation looks like. Empty provenance is stated, not hidden."""
        source = self.metadata.get("source_title") or "(来源未记录)"
        level = self.metadata.get("evidence_level", "")
        return f"{source}｜{level}" if level else source


@dataclass
class KnowledgeStore:
    """Holds the corpus and answers queries.

    ``collection`` defaults to a per-instance unique name because
    ``chromadb.EphemeralClient()`` hands back a *shared* client for identical
    settings. With a fixed name, building a second store silently deletes the
    first one's collection — which breaks exactly the thing this is for, namely
    holding two stores side by side to compare embedders.
    """

    embedder: Embedder
    persist_dir: Path | None = None
    collection: str = field(default_factory=lambda: f"{COLLECTION}-{uuid4().hex[:8]}")
    _collection: Any = field(default=None, repr=False)
    _cards: dict[str, KnowledgeCard] = field(default_factory=dict, repr=False)

    def _client(self) -> Any:
        import chromadb

        if self.persist_dir is None:
            return chromadb.EphemeralClient()
        return chromadb.PersistentClient(path=str(self.persist_dir))

    def build(self, cards: list[KnowledgeCard]) -> int:
        """(Re)build the collection from scratch. Returns the number indexed."""
        client = self._client()
        with contextlib.suppress(Exception):
            # Absent on a fresh client, which is the normal case.
            client.delete_collection(self.collection)

        collection = client.create_collection(
            name=self.collection,
            # Cosine rather than Chroma's default L2: the embeddings are normalised
            # and cosine is what the provider's similarity is defined against.
            metadata={"hnsw:space": "cosine"},
        )
        documents = [card.as_document() for card in cards]
        collection.add(
            ids=[card.id for card in cards],
            documents=documents,
            embeddings=self.embedder.embed(documents),
            metadatas=[card.metadata() for card in cards],
        )
        self._collection = collection
        self._cards = {card.id: card for card in cards}
        return len(cards)

    def query(
        self,
        text: str,
        *,
        top_k: int = 3,
        material: str | None = None,
    ) -> list[Retrieved]:
        """Nearest cards, optionally restricted to a material.

        The filter runs before ranking rather than after, so asking for three
        results returns three *applicable* ones rather than three candidates of
        which some are then discarded.
        """
        if self._collection is None:
            msg = "store has not been built"
            raise RuntimeError(msg)

        where = {f"{MATERIAL_PREFIX}{material}": True} if material else None
        result = self._collection.query(
            query_embeddings=self.embedder.embed([text]),
            n_results=min(top_k, max(1, len(self._cards))),
            where=where,
        )

        out: list[Retrieved] = []
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        for card_id, distance, metadata in zip(ids, distances, metadatas, strict=False):
            card = self._cards[card_id]
            out.append(
                Retrieved(
                    card_id=card_id,
                    title=card.title,
                    body=card.body,
                    # Chroma reports cosine *distance*; similarity is the useful
                    # direction to read and to threshold on.
                    score=1.0 - float(distance),
                    metadata=dict(metadata),
                )
            )
        return out

    @property
    def size(self) -> int:
        return len(self._cards)
