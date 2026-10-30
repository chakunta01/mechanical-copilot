"""Pydantic v2 API schemas: request/response contracts shared by routes and services."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def coerce_str_list(v: Any) -> list[str]:
    """Lenient coercion for LLM-produced string lists.

    Small models sometimes emit [{"document_id": ...}] objects where the schema
    says list[str]. Coerce dict elements to a readable string instead of failing
    the whole generation.
    """
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        out: list[str] = []
        for item in v:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                # Prefer the most descriptive key the model tends to fill.
                for key in ("document_id", "title", "name", "description", "source"):
                    if key in item and isinstance(item[key], str):
                        out.append(item[key])
                        break
                else:
                    out.append(
                        ", ".join(f"{k}={item[k]}" for k in item if isinstance(item[k], str)) or str(item)
                    )
            elif item is not None:
                out.append(str(item))
        return out
    return [str(v)]

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterIn(BaseModel):
    email: EmailStr
    # bcrypt operates on max 72 bytes; cap here so hashing never truncates silently.
    password: str = Field(min_length=10, max_length=72)
    full_name: str = Field(default="", max_length=255)
    admin_bootstrap_token: str = Field(default="", max_length=256)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - standard JWT auth scheme label, not a secret


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(ORMModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool


class UsersOut(BaseModel):
    items: list[UserOut]


class RoleIn(BaseModel):
    role: Literal["admin", "engineer", "viewer"]


# --------------------------------------------------------------------------- #
# Knowledge base
# --------------------------------------------------------------------------- #
class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    doc_type: Literal["sop", "routing", "standard", "lesson", "qa"] = "sop"
    source_ref: str = Field(default="", max_length=512)
    version: str = Field(default="v1", max_length=64)
    content: str = Field(min_length=1)


class DocumentOut(ORMModel):
    id: str
    title: str
    doc_type: str
    source_ref: str
    version: str
    status: str
    chunk_count: int
    error: str
    created_at: datetime


class DocumentsOut(BaseModel):
    items: list[DocumentOut]
    total: int


class Citation(BaseModel):
    document_id: str
    title: str
    source_ref: str
    version: str
    chunk_id: str
    score: float
    snippet: str


class RetrievedChunk(Citation):
    ordinal: int


class SearchOut(BaseModel):
    query: str
    chunks: list[Citation]


# --------------------------------------------------------------------------- #
# Process planning
# --------------------------------------------------------------------------- #
class PlannerRequirements(BaseModel):
    part_number: str = Field(min_length=1, max_length=128)
    material: str = Field(default="", max_length=128)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    tolerance_notes: str = ""
    surface_finish: str = ""
    features: list[str] = Field(default_factory=list)
    special_requirements: list[str] = Field(default_factory=list)
    notes: str = ""


class PlanGenerateIn(BaseModel):
    requirements: PlannerRequirements
    title: str | None = Field(default=None, max_length=512)


class OperationOut(BaseModel):
    op_number: int
    name: str
    machine: str
    tooling: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    inspection_checkpoints: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class InspectionPlanItem(BaseModel):
    characteristic: str
    method: str
    frequency: str
    acceptance_criteria: str
    references: list[str] = Field(default_factory=list)

    @field_validator("references", mode="before")
    @classmethod
    def _coerce_references(cls, v: Any) -> list[str]:
        return coerce_str_list(v)


class ValidationIssue(BaseModel):
    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str
    field: str = ""


class RuleValidationReport(BaseModel):
    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    checked_at: datetime | None = None


class GroundingReport(BaseModel):
    citation_count: int = 0
    operations_with_citations: int = 0
    total_operations: int = 0
    unsupported_claims: list[str] = Field(default_factory=list)


class ProcessPlanOut(ORMModel):
    id: str
    title: str
    part_number: str
    material: str
    quantity: int
    requirements: dict[str, Any]
    plan: dict[str, Any]
    status: str
    version: int
    validation: dict[str, Any]
    grounding: dict[str, Any]
    rejected_reason: str
    owner_id: str
    created_at: datetime
    updated_at: datetime


class PlansOut(BaseModel):
    items: list[ProcessPlanOut]
    total: int


class ApprovalOut(ORMModel):
    id: str
    plan_id: str
    action: str
    actor_id: str
    actor_name: str
    comment: str
    created_at: datetime


class ApprovalsOut(BaseModel):
    items: list[ApprovalOut]


class PlanDecisionIn(BaseModel):
    action: Literal["submit", "approve", "reject", "revise"]
    comment: str = ""
    revised_plan: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #
class Defect(BaseModel):
    defect_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    location: str = ""
    bbox: list[float] | None = None  # normalized [x, y, w, h]
    evidence: str = ""


class InspectionResult(BaseModel):
    verdict: Literal["pass", "fail", "inconclusive"]
    confidence: float = Field(ge=0.0, le=1.0)
    defects: list[Defect] = Field(default_factory=list)
    explanation: str = ""
    recommended_disposition: Literal["accept", "reject", "rework", "review"]
    references: list[Citation] = Field(default_factory=list)


class InspectionOut(ORMModel):
    id: str
    part_number: str
    status: str
    quality: dict[str, Any]
    result: dict[str, Any]
    disposition: str
    reviewed_by: str
    reviewed_at: datetime | None
    created_at: datetime


class InspectionsOut(BaseModel):
    items: list[InspectionOut]
    total: int


class DispositionIn(BaseModel):
    disposition: Literal["accept", "reject", "rework"]
    notes: str = ""


# --------------------------------------------------------------------------- #
# Feedback
# --------------------------------------------------------------------------- #
class FeedbackIn(BaseModel):
    target_type: Literal["plan", "inspection", "qa"]
    target_id: str = Field(min_length=1, max_length=32)
    rating: int = Field(ge=1, le=5)
    category: Literal["correctness", "grounding", "usefulness", "safety", "other"] = "other"
    correction: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class FeedbackOut(ORMModel):
    id: str
    target_type: str
    target_id: str
    rating: int
    category: str
    correction: dict[str, Any]
    notes: str
    actor_id: str
    created_at: datetime


class FeedbackOutList(BaseModel):
    items: list[FeedbackOut]
    total: int


# --------------------------------------------------------------------------- #
# Q&A
# --------------------------------------------------------------------------- #
class QaAskIn(BaseModel):
    thread_id: str | None = None
    question: str = Field(min_length=3, max_length=4000)


class QaImageGenerateIn(BaseModel):
    thread_id: str | None = None
    prompt: str = Field(min_length=3, max_length=4000)


class QaMediaOut(BaseModel):
    id: str
    kind: Literal["image", "video"]
    mime_type: str
    url: str
    prompt: str
    created_at: datetime


class QaMessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float
    attachments: list[QaMediaOut] = Field(default_factory=list)
    created_at: datetime


class QaThreadOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    messages: list[QaMessageOut] = Field(default_factory=list)


class QaThreadsOut(BaseModel):
    items: list[QaThreadOut]


class QaAnswer(BaseModel):
    thread_id: str
    answer: str
    citations: list[Citation]
    confidence: float
    refused: bool = False
    refusal_reason: str = ""
    # grounded = answered from the approved KB with citations;
    # general = question was outside the KB, answered from the LLM's broad knowledge.
    mode: Literal["grounded", "general"] = "grounded"


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
class DashboardStats(BaseModel):
    total_plans: int
    plans_by_status: dict[str, int]
    total_inspections: int
    defect_rate: float
    avg_plan_rating: float
    total_documents: int
    total_feedback: int
    recent_approvals: list[ApprovalOut]


class HealthOut(BaseModel):
    status: str
    version: str
    llm_provider: str
    embeddings_provider: str
    vector_store: str
    database: str
