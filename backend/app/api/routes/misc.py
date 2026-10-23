"""Feedback, Q&A, dashboard, and admin routes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.errors import Forbidden, NotFound
from app.models import (
    Approval,
    AuditLog,
    Document,
    Feedback,
    Inspection,
    ProcessPlan,
    QaMessage,
    QaThread,
    Role,
    User,
)
from app.schemas import (
    ApprovalOut,
    DashboardStats,
    FeedbackIn,
    FeedbackOut,
    FeedbackOutList,
    QaAnswer,
    QaAskIn,
    QaThreadOut,
    QaThreadsOut,
    UserOut,
    UsersOut,
)
from app.services.qa import ask as qa_service_ask

router = APIRouter(tags=["misc"])


# ------------------------------- Feedback ---------------------------------- #
@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def submit_feedback(payload: FeedbackIn, user: CurrentUser, db: DbSession) -> FeedbackOut:
    fb = Feedback(
        id=f"fdb_{__import__('uuid').uuid4().hex[:20]}",
        target_type=payload.target_type,
        target_id=payload.target_id,
        rating=payload.rating,
        category=payload.category,
        correction=payload.correction,
        notes=payload.notes,
        actor_id=user.id,
    )
    db.add(fb)
    db.flush()
    return FeedbackOut.model_validate(fb)


@router.get("/feedback", response_model=FeedbackOutList)
def list_feedback(user: CurrentUser, db: DbSession, target_type: str = "", limit: int = 50) -> FeedbackOutList:
    query = select(Feedback).order_by(Feedback.created_at.desc())
    if target_type:
        query = query.where(Feedback.target_type == target_type)
    items = db.scalars(query.limit(min(limit, 200))).all()
    total = db.scalar(select(func.count()).select_from(Feedback)) or 0
    return FeedbackOutList(items=[FeedbackOut.model_validate(f) for f in items], total=total)


# ---------------------------------- Q&A ------------------------------------ #
@router.post("/qa/ask", response_model=QaAnswer)
def qa_ask(payload: QaAskIn, user: CurrentUser, db: DbSession) -> QaAnswer:
    return qa_service_ask(db, user_id=user.id, thread_id=payload.thread_id, question=payload.question)


@router.get("/qa/threads", response_model=QaThreadsOut)
def qa_threads(user: CurrentUser, db: DbSession) -> QaThreadsOut:
    threads = db.scalars(
        select(QaThread).where(QaThread.user_id == user.id).order_by(QaThread.created_at.desc()).limit(50)
    ).all()
    out = []
    for t in threads:
        msgs = db.scalars(
            select(QaMessage).where(QaMessage.thread_id == t.id).order_by(QaMessage.id.asc())
        ).all()
        out.append(
            {
                "id": t.id,
                "title": t.title,
                "created_at": t.created_at,
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "citations": m.citations or [],
                        "confidence": m.confidence,
                        "created_at": m.created_at,
                    }
                    for m in msgs
                ],
            }
        )
    return QaThreadsOut(items=[QaThreadOut.model_validate(d) for d in out])


# -------------------------------- Dashboard -------------------------------- #
@router.get("/dashboard", response_model=DashboardStats)
def dashboard(user: CurrentUser, db: DbSession) -> DashboardStats:
    total_plans = db.scalar(select(func.count()).select_from(ProcessPlan)) or 0
    by_status_rows = db.execute(
        select(ProcessPlan.status, func.count()).group_by(ProcessPlan.status)
    ).all()
    plans_by_status = {s.value if hasattr(s, "value") else str(s): c for s, c in by_status_rows}

    total_inspections = db.scalar(select(func.count()).select_from(Inspection)) or 0
    failed = db.scalar(
        select(func.count())
        .select_from(Inspection)
        .where(Inspection.result["verdict"].as_string() == "fail")
    ) or 0
    defect_rate = (failed / total_inspections) if total_inspections else 0.0

    avg_rating = db.scalar(select(func.avg(Feedback.rating))) or 0.0
    total_documents = db.scalar(select(func.count()).select_from(Document)) or 0
    total_feedback = db.scalar(select(func.count()).select_from(Feedback)) or 0

    approvals = db.scalars(select(Approval).order_by(Approval.created_at.desc()).limit(8)).all()

    return DashboardStats(
        total_plans=total_plans,
        plans_by_status=plans_by_status,
        total_inspections=total_inspections,
        defect_rate=round(defect_rate, 4),
        avg_plan_rating=round(float(avg_rating), 2),
        total_documents=total_documents,
        total_feedback=total_feedback,
        recent_approvals=[ApprovalOut.model_validate(a) for a in approvals],
    )


# ------------------------------ Admin / audit ------------------------------ #
@router.get("/admin/users", response_model=UsersOut)
def list_users(admin: AdminUser, db: DbSession) -> UsersOut:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return UsersOut(items=[UserOut.model_validate(u) for u in users])


@router.patch("/admin/users/{user_id}/role", response_model=UserOut)
def set_role(user_id: str, role: str, admin: AdminUser, db: DbSession) -> UserOut:
    if role not in Role.__members__:
        raise NotFound("Unknown role")
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    if user.id == admin.id:
        raise Forbidden("Cannot change your own role")
    user.role = Role(role)
    db.flush()
    return UserOut.model_validate(user)


@router.get("/admin/audit", response_model=list[dict])
def audit_tail(user: AdminUser, db: DbSession, limit: int = 100) -> list[dict]:
    logs = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
    return [
        {
            "id": entry.id,
            "request_id": entry.request_id,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "detail": entry.detail,
            "created_at": entry.created_at,
        }
        for entry in logs
    ]
