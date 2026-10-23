"""SQLAlchemy ORM models: users, documents, chunks, plans, inspections, feedback, audit."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------- #
# Users & auth
# --------------------------------------------------------------------------- #
class Role(str, enum.Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.ENGINEER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    plans: Mapped[list["ProcessPlan"]] = relationship(back_populates="owner")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- #
# Knowledge base
# --------------------------------------------------------------------------- #
class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    INGESTED = "ingested"
    FAILED = "failed"


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    doc_type: Mapped[str] = mapped_column(String(64), default="sop")  # sop|routing|standard|lesson|qa
    source_ref: Mapped[str] = mapped_column(String(512), default="")  # e.g. "SOP-MILL-001 §4.2"
    version: Mapped[str] = mapped_column(String(64), default="v1")
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    file_path: Mapped[str] = mapped_column(String(1024), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(32), default="system")

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all,delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


Index("ix_chunks_doc_ordinal", Chunk.document_id, Chunk.ordinal)


# --------------------------------------------------------------------------- #
# Process planning
# --------------------------------------------------------------------------- #
class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ProcessPlan(Base, TimestampMixin):
    __tablename__ = "process_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    part_number: Mapped[str] = mapped_column(String(128), index=True)
    material: Mapped[str] = mapped_column(String(128), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)  # raw structured input
    plan: Mapped[dict] = mapped_column(JSON, default=dict)  # full structured plan payload
    status: Mapped[PlanStatus] = mapped_column(Enum(PlanStatus), default=PlanStatus.DRAFT)
    version: Mapped[int] = mapped_column(Integer, default=1)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)  # rule engine report
    grounding: Mapped[dict] = mapped_column(JSON, default=dict)  # citations, unsupported-claim flags
    rejected_reason: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    owner: Mapped[User] = relationship(back_populates="plans")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="plan", cascade="all,delete-orphan")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("process_plans.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # submitted|approved|rejected|revised
    actor_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # plan snapshot at action time
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    plan: Mapped[ProcessPlan] = relationship(back_populates="approvals")


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #
class InspectionStatus(str, enum.Enum):
    PENDING = "pending"
    ANALYZED = "analyzed"
    FAILED = "failed"


class Inspection(Base, TimestampMixin):
    __tablename__ = "inspections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    part_number: Mapped[str] = mapped_column(String(128), index=True, default="")
    image_path: Mapped[str] = mapped_column(String(1024))
    thumbnail_path: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[InspectionStatus] = mapped_column(Enum(InspectionStatus), default=InspectionStatus.PENDING)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)  # image quality gate report
    result: Mapped[dict] = mapped_column(JSON, default=dict)  # defect verdict + evidence
    disposition: Mapped[str] = mapped_column(String(32), default="pending")  # accept|reject|rework|pending
    reviewed_by: Mapped[str] = mapped_column(String(255), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)


# --------------------------------------------------------------------------- #
# Feedback (human corrections -> continuous improvement) & audit
# --------------------------------------------------------------------------- #
class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)  # plan|inspection|qa
    target_id: Mapped[str] = mapped_column(String(32), index=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)  # 1-5 rubric
    category: Mapped[str] = mapped_column(String(32), default="")  # correctness|grounding|usefulness|safety
    correction: Mapped[dict] = mapped_column(JSON, default=dict)  # structured edit diff
    notes: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), default="")
    actor_id: Mapped[str] = mapped_column(String(32), default="anonymous", index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- #
# Q&A (grounded engineering assistant)
# --------------------------------------------------------------------------- #
class QaThread(Base):
    __tablename__ = "qa_threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New thread")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QaMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("qa_threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
