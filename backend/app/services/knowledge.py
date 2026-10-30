"""Knowledge service: ingestion pipeline and retrieval with citations.

Ingestion: extract text -> chunk -> embed -> upsert vectors -> mark document INGESTED.
Retrieval: embed query -> vector search -> optional keyword boost -> Citation objects.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Chunk, Document, DocumentStatus
from app.schemas import Citation
from app.services.chunker import chunk_text, extract_text_from_docx, extract_text_from_pdf
from app.services.embeddings import get_embeddings
from app.services.vector_store import VectorRecord, get_vector_store

logger = get_logger("knowledge")


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def ingest_document(
    db: Session,
    *,
    document: Document,
    content: str | None = None,
    file_bytes: bytes | None = None,
) -> Document:
    """Chunk + embed + index a document. Idempotent: replaces previous vectors."""
    try:
        if file_bytes is not None:
            name = document.file_path.lower()
            if name.endswith(".pdf"):
                content = extract_text_from_pdf(file_bytes)
            elif name.endswith(".docx"):
                content = extract_text_from_docx(file_bytes)
            else:
                content = file_bytes.decode("utf-8", errors="replace")

        if not content or not content.strip():
            raise ValueError("No extractable text content")

        chunks = chunk_text(content)
        if not chunks:
            raise ValueError("Chunking produced no chunks")

        embeddings = get_embeddings()
        vectors = embeddings.embed([c.text for c in chunks])

        store = get_vector_store()
        store.delete_document(document.id)

        records: list[VectorRecord] = []
        db.query(Chunk).filter(Chunk.document_id == document.id).delete()
        for chunk, vec in zip(chunks, vectors, strict=True):
            row = Chunk(
                id=f"chk_{document.id[4:]}_{chunk.ordinal:04d}",
                document_id=document.id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                meta={**chunk.meta, "doc_type": document.doc_type, "version": document.version},
            )
            db.add(row)
            records.append(
                VectorRecord(
                    chunk_id=row.id,
                    document_id=document.id,
                    vector=vec,
                    text=chunk.text,
                    meta={
                        "title": document.title,
                        "doc_type": document.doc_type,
                        "source_ref": document.source_ref,
                        "version": document.version,
                        "section": chunk.section,
                    },
                )
            )
        store.upsert(records)
        _off_topic_baseline_cached.cache_clear()

        document.status = DocumentStatus.INGESTED
        document.chunk_count = len(chunks)
        document.error = ""
        db.flush()
        logger.info("ingested", extra={"event": "ingested", "actor": document.id})
        return document

    except Exception as exc:
        document.status = DocumentStatus.FAILED
        document.error = str(exc)[:1000]
        db.flush()
        logger.warning("ingest_failed doc=%s err=%s", document.id, exc)
        return document


def rebuild_index_from_db(db: Session) -> int:
    """Rebuild the in-memory vector store after a process restart."""
    store = get_vector_store()
    if store.name != "numpy":
        return store.count()

    docs = db.query(Document).filter(Document.status == DocumentStatus.INGESTED).all()
    doc_by_id = {d.id: d for d in docs}
    chunks = db.query(Chunk).filter(Chunk.document_id.in_(doc_by_id)).all() if doc_by_id else []
    records = [
        VectorRecord(
            chunk_id=c.id,
            document_id=c.document_id,
            vector=[],  # vectors are re-derived below
            text=c.text,
            meta={
                "title": doc_by_id[c.document_id].title,
                "doc_type": doc_by_id[c.document_id].doc_type,
                "source_ref": doc_by_id[c.document_id].source_ref,
                "version": doc_by_id[c.document_id].version,
                "section": (c.meta or {}).get("section", ""),
            },
        )
        for c in chunks
    ]
    if records:
        embeddings = get_embeddings()
        vecs = embeddings.embed([r.text for r in records])
        for r, v in zip(records, vecs, strict=True):
            r.vector = v
        store.upsert(records)
    return len(records)


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def _keyword_boost(query: str, text: str) -> float:
    """Light lexical overlap score in [0, 1] over meaningful (non-stopword) tokens."""
    from app.services.embeddings import _STOPWORDS

    q_tokens = {t for t in query.lower().split() if t not in _STOPWORDS and len(t) > 1}
    if not q_tokens:
        return 0.0
    t_tokens = set(text.lower().split())
    return len(q_tokens & t_tokens) / len(q_tokens)


def retrieve(
    query: str,
    *,
    top_k: int | None = None,
    doc_types: list[str] | None = None,
    min_score: float | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """Retrieve cited chunks for a query. Returns citation-shaped dicts."""
    from app.core.config import settings
    from app.schemas import Citation

    top_k = top_k or settings.retrieval_top_k
    min_score = settings.retrieval_min_score if min_score is None else min_score

    embeddings = get_embeddings()
    # Provider-aware floor: hashing mode is the offline/dev path; keep its floor
    # low (calibrated scores compress the band) and rely on the QA separation
    # gate for refusal quality instead of a high absolute cutoff.
    if embeddings.name == "hashing":
        min_score = min(min_score, 0.05)
    q_vec = embeddings.embed_one(query)
    store = get_vector_store()

    allowed_docs: list[str] | None = None
    if doc_types or user_id:
        ids = db_query_doc_ids(doc_types, user_id=user_id)
        allowed_docs = ids if ids else ["__none__"]

    hits = store.search(q_vec, top_k=top_k * 2, document_ids=allowed_docs)

    # Hybrid: blend dense score with lexical overlap (dense 0.8 / lexical 0.2).
    blended: list[tuple[dict, float]] = []
    for rec, score in hits:
        lex = _keyword_boost(query, rec.text)
        final = 0.8 * score + 0.2 * lex
        citation = Citation(
            document_id=rec.document_id,
            title=str(rec.meta.get("title", "")),
            source_ref=str(rec.meta.get("source_ref", "")),
            version=str(rec.meta.get("version", "")),
            chunk_id=rec.chunk_id,
            score=round(final, 4),
            snippet=rec.text[:280],
        ).model_dump()
        blended.append((citation, final))

    # Provider calibration: hashing features yield compressed cosine scores
    # (~0.10-0.35 meaningful) vs semantic models (~0.3-0.9). Rescale the hashing
    # band onto [0, 1] so thresholds (min_score, QA refusal) behave identically
    # regardless of the embedding provider configured.
    if embeddings.name == "hashing":
        lo, hi = 0.14, 0.34
        blended = [
            (c, round(min(1.0, max(0.0, (s - lo) / (hi - lo))), 4)) for c, s in blended
        ]

    blended = [b for b in blended if b[1] >= min_score]
    blended.sort(key=lambda t: t[1], reverse=True)
    return [c for c, _ in blended[:top_k]]


def retrieval_stats(query: str) -> dict:
    """Score-distribution stats for a query across the whole store.

    Used by the Q&A refusal gate: a question that genuinely matches the corpus
    produces a top score well ABOVE the corpus mean for that query; a question
    about nothing in the corpus scores uniformly low (separation ~1.0).
    Self-calibrating for any embedding provider and any chunk size.
    """
    embeddings = get_embeddings()
    q_vec = embeddings.embed_one(query)
    hits = get_vector_store().search(q_vec, top_k=10_000)
    if not hits:
        return {"n": 0, "top": 0.0, "mean": 0.0, "separation": 0.0}
    scores = [s for _, s in hits]
    top = max(scores)
    mean = sum(scores) / len(scores)
    separation = top / mean if mean > 1e-6 else 0.0
    return {"n": len(scores), "top": round(top, 4), "mean": round(mean, 4), "separation": round(separation, 3)}


# Domain-irrelevant probe questions used to calibrate the "off-topic floor" of
# the embedding space at runtime. Their best corpus similarity defines the
# baseline that a real question must clear (with margin) before we answer.
# This keeps the anti-hallucination refusal gate self-calibrating for any
# embedding model and any corpus size.
_OFF_TOPIC_PROBES = (
    "quarterly financial report revenue forecast",
    "recipe for baking chocolate chip cookies at home",
    "how to change a flat tire on a highway",
    "best exercises for lower back pain relief",
    "popular tourist attractions in southern Europe",
)


def off_topic_baseline(user_id: str | None = None) -> float:
    """Best corpus similarity for known-irrelevant questions, using the active
    embedding provider. Probe embeddings are cached until the indexed corpus changes."""
    from app.core.config import settings

    embeddings = get_embeddings()
    store = get_vector_store()
    document_ids = tuple(sorted(db_query_doc_ids(user_id=user_id))) if user_id else None
    return _off_topic_baseline_cached(
        embeddings.name,
        settings.embeddings_model,
        store.count(),
        document_ids,
    )


@lru_cache(maxsize=128)
def _off_topic_baseline_cached(
    embedding_name: str,
    embedding_model: str,
    vector_count: int,
    document_ids: tuple[str, ...] | None,
) -> float:
    """Cache probe work by embedding config and indexed document corpus."""
    del embedding_name, embedding_model, vector_count  # used as cache-key components
    embeddings = get_embeddings()
    vectors = embeddings.embed(list(_OFF_TOPIC_PROBES))
    store = get_vector_store()
    scoped_documents = list(document_ids) if document_ids is not None else None
    tops = []
    for vector in vectors:
        hits = store.search(vector, top_k=1, document_ids=scoped_documents)
        if hits:
            tops.append(hits[0][1])
    return max(tops) if tops else 0.0


def db_query_doc_ids(doc_types: list[str] | None = None, *, user_id: str | None = None) -> list[str]:
    """Lookup document ids filtered by type; isolated here to keep retrieve() pure-ish."""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        query = select(Document.id)
        if doc_types:
            query = query.where(Document.doc_type.in_(doc_types))
        if user_id:
            query = query.where(Document.created_by.in_(["system", user_id]))
        rows = db.execute(query).all()
        return [r[0] for r in rows]


def citation_of(chunk: Chunk, document: Document, score: float) -> dict:
    return Citation(
        document_id=document.id,
        title=document.title,
        source_ref=document.source_ref,
        version=document.version,
        chunk_id=chunk.id,
        score=round(score, 4),
        snippet=chunk.text[:280],
    ).model_dump()
