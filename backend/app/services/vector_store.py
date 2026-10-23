"""Vector store abstraction.

- NumpyVectorStore: exact cosine similarity over an in-memory index rebuilt from
  the database at startup and on ingestion. Zero extra infra; right for single-node
  deployments and dev.
- ChromaVectorStore: optional persistent store (pip install .[chroma]).

Both implement upsert/delete/search so the retrieval layer is storage-agnostic.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("vector")


class VectorRecord:
    __slots__ = ("chunk_id", "document_id", "vector", "text", "meta")

    def __init__(self, chunk_id: str, document_id: str, vector: list[float], text: str, meta: dict) -> None:
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.vector = vector
        self.text = text
        self.meta = meta


class BaseVectorStore(ABC):
    name: str = "base"

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> int: ...

    @abstractmethod
    def delete_document(self, document_id: str) -> int: ...

    @abstractmethod
    def search(self, query_vec: list[float], top_k: int, document_ids: list[str] | None = None) -> list[tuple[VectorRecord, float]]: ...

    @abstractmethod
    def count(self) -> int: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class NumpyVectorStore(BaseVectorStore):
    name = "numpy"

    def __init__(self) -> None:
        self._by_doc: dict[str, list[VectorRecord]] = {}

    def upsert(self, records: list[VectorRecord]) -> int:
        for r in records:
            bucket = self._by_doc.setdefault(r.document_id, [])
            bucket[:] = [x for x in bucket if x.chunk_id != r.chunk_id]
            bucket.append(r)
        return len(records)

    def delete_document(self, document_id: str) -> int:
        return len(self._by_doc.pop(document_id, []))

    def search(
        self, query_vec: list[float], top_k: int, document_ids: list[str] | None = None
    ) -> list[tuple[VectorRecord, float]]:
        scored: list[tuple[VectorRecord, float]] = []
        docs = self._by_doc if document_ids is None else {d: self._by_doc[d] for d in document_ids if d in self._by_doc}
        for bucket in docs.values():
            for rec in bucket:
                scored.append((rec, _cosine(query_vec, rec.vector)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return sum(len(v) for v in self._by_doc.values())


class ChromaVectorStore(BaseVectorStore):
    name = "chroma"

    def __init__(self, persist_dir: str) -> None:
        import chromadb  # optional dependency

        self.client = chromadb.PersistentClient(path=str(Path(persist_dir)))
        self.collection = self.client.get_or_create_collection("knowledge")

    def upsert(self, records: list[VectorRecord]) -> int:
        if not records:
            return 0
        self.collection.upsert(
            ids=[r.chunk_id for r in records],
            embeddings=[r.vector for r in records],
            documents=[r.text for r in records],
            metadatas=[
                {"document_id": r.document_id, "meta": json.dumps(r.meta, default=str)} for r in records
            ],
        )
        return len(records)

    def delete_document(self, document_id: str) -> int:
        got = self.collection.get(where={"document_id": document_id})
        n = len(got["ids"])
        if n:
            self.collection.delete(ids=got["ids"])
        return n

    def search(
        self, query_vec: list[float], top_k: int, document_ids: list[str] | None = None
    ) -> list[tuple[VectorRecord, float]]:
        where = {"document_id": {"$in": document_ids}} if document_ids else None
        res = self.collection.query(query_embeddings=[query_vec], n_results=top_k, where=where)
        out: list[tuple[VectorRecord, float]] = []
        for i in range(len(res["ids"][0])):
            meta = json.loads(res["metadatas"][0][i].get("meta", "{}"))
            rec = VectorRecord(
                chunk_id=res["ids"][0][i],
                document_id=res["metadatas"][0][i]["document_id"],
                vector=[],
                text=res["documents"][0][i],
                meta=meta,
            )
            out.append((rec, 1.0 - float(res["distances"][0][i])))
        return out

    def count(self) -> int:
        return self.collection.count()


_store: BaseVectorStore | None = None


def get_vector_store() -> BaseVectorStore:
    global _store
    if _store is None:
        if settings.vector_store == "chroma":
            try:
                _store = ChromaVectorStore(settings.chroma_dir)
            except ImportError:
                logger.warning("chromadb not installed; falling back to numpy store")
                _store = NumpyVectorStore()
        else:
            _store = NumpyVectorStore()
    return _store
