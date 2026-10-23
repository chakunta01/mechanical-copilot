"""Knowledge base routes: document CRUD, file upload ingestion, semantic search."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, EngineerUser
from app.core.config import settings
from app.core.errors import NotFound, PayloadTooLarge, UnsupportedMediaType
from app.models import AuditLog, Chunk, Document
from app.schemas import Citation, DocumentIn, DocumentOut, DocumentsOut, SearchOut
from app.services import knowledge

router = APIRouter(prefix="/documents", tags=["knowledge"])

ALLOWED_DOC_MIME = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
ALLOWED_DOC_EXT = {".txt", ".md", ".pdf", ".docx"}


@router.post("", response_model=DocumentOut, status_code=201)
def create_document(payload: DocumentIn, user: EngineerUser, db: DbSession) -> DocumentOut:
    doc = Document(
        id=f"doc_{uuid.uuid4().hex[:20]}",
        title=payload.title,
        doc_type=payload.doc_type,
        source_ref=payload.source_ref,
        version=payload.version,
        file_path="inline",
        created_by=user.id,
    )
    db.add(doc)
    db.flush()
    knowledge.ingest_document(db, document=doc, content=payload.content)
    db.add(
        AuditLog(
            actor_id=user.id,
            action="document.ingested",
            target_type="document",
            target_id=doc.id,
            detail={"chunks": doc.chunk_count, "status": doc.status.value},
        )
    )
    return DocumentOut.model_validate(doc)


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile,
    user: EngineerUser,
    db: DbSession,
    title: str = "",
    doc_type: str = "sop",
    source_ref: str = "",
) -> DocumentOut:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_DOC_EXT:
        raise UnsupportedMediaType(f"Allowed: {', '.join(sorted(ALLOWED_DOC_EXT))}")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise PayloadTooLarge(f"Max {settings.max_upload_mb} MB")

    upload_dir = Path(settings.upload_dir) / "documents"
    upload_dir.mkdir(parents=True, exist_ok=True)
    doc_id = f"doc_{uuid.uuid4().hex[:20]}"
    file_path = upload_dir / f"{doc_id}{ext}"
    file_path.write_bytes(data)

    doc = Document(
        id=doc_id,
        title=title or (file.filename or "Untitled"),
        doc_type=doc_type,
        source_ref=source_ref or file.filename or "",
        file_path=str(file_path),
        created_by=user.id,
    )
    db.add(doc)
    db.flush()
    knowledge.ingest_document(db, document=doc, file_bytes=data)
    return DocumentOut.model_validate(doc)


@router.get("", response_model=DocumentsOut)
def list_documents(user: CurrentUser, db: DbSession, q: str = "", limit: int = 50, offset: int = 0) -> DocumentsOut:
    query = select(Document).order_by(Document.created_at.desc())
    if q:
        query = query.where(Document.title.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(Document)) or 0
    docs = db.scalars(query.limit(min(limit, 200)).offset(offset)).all()
    return DocumentsOut(items=[DocumentOut.model_validate(d) for d in docs], total=total)


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, user: CurrentUser, db: DbSession) -> DocumentOut:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise NotFound("Document not found")
    return DocumentOut.model_validate(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: EngineerUser, db: DbSession) -> None:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise NotFound("Document not found")
    knowledge.get_vector_store().delete_document(doc_id)
    db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
    db.delete(doc)
    db.add(AuditLog(actor_id=user.id, action="document.deleted", target_type="document", target_id=doc_id))


@router.post("/reindex", status_code=200)
def reindex(user: EngineerUser, db: DbSession) -> dict:
    count = knowledge.rebuild_index_from_db(db)
    return {"indexed_chunks": count, "store": knowledge.get_vector_store().name}


@router.post("/search", response_model=SearchOut)
def search(payload: dict, user: CurrentUser, db: DbSession) -> SearchOut:
    question = str(payload.get("query", "")).strip()
    if not question:
        raise NotFound("query required")
    citations = knowledge.retrieve(question, top_k=8)
    return SearchOut(query=question, chunks=[Citation.model_validate(c) for c in citations])
