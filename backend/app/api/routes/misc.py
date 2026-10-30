"""Feedback, Q&A, dashboard, and admin routes."""

from __future__ import annotations

import base64
import hashlib
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import Forbidden, NotFound, PayloadTooLarge, UpstreamError
from app.core.logging import get_logger
from app.models import (
    Approval,
    AuditLog,
    Document,
    Feedback,
    Inspection,
    ProcessPlan,
    QaMessage,
    QaMedia,
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
    QaImageGenerateIn,
    QaMediaOut,
    QaThreadOut,
    QaThreadsOut,
    UserOut,
    UsersOut,
)
from app.services.qa import ask as qa_service_ask

router = APIRouter(tags=["misc"])
logger = get_logger("misc")


# ------------------------------- Feedback ---------------------------------- #
@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def submit_feedback(payload: FeedbackIn, user: CurrentUser, db: DbSession) -> FeedbackOut:
    target_model = {"plan": ProcessPlan, "inspection": Inspection, "qa": QaThread}[payload.target_type]
    owner_field = target_model.owner_id if payload.target_type in ("plan", "inspection") else target_model.user_id
    target = db.scalar(select(target_model.id).where(target_model.id == payload.target_id, owner_field == user.id))
    if target is None:
        raise NotFound("Feedback target not found")
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
    query = select(Feedback).where(Feedback.actor_id == user.id).order_by(Feedback.created_at.desc())
    if target_type:
        query = query.where(Feedback.target_type == target_type)
    items = db.scalars(query.limit(min(limit, 200))).all()
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
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
        media = db.scalars(
            select(QaMedia).where(QaMedia.thread_id == t.id, QaMedia.user_id == user.id)
        ).all()
        media_by_message: dict[int, list[QaMedia]] = {}
        for attachment in media:
            media_by_message.setdefault(attachment.message_id, []).append(attachment)
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
                        "attachments": [
                            QaMediaOut(
                                id=item.id,
                                kind=item.kind,
                                mime_type=item.mime_type,
                                url=f"/api/v1/qa/media/{item.id}",
                                prompt=item.prompt,
                                created_at=item.created_at,
                            ).model_dump(mode="json")
                            for item in media_by_message.get(m.id, [])
                        ],
                    }
                    for m in msgs
                ],
            }
        )
    return QaThreadsOut(items=[QaThreadOut.model_validate(d) for d in out])


@router.delete("/qa/threads/{thread_id}", status_code=204)
def delete_qa_thread(thread_id: str, user: CurrentUser, db: DbSession) -> Response:
    """Delete one conversation and its generated media for its owner only."""
    thread = db.scalar(select(QaThread).where(QaThread.id == thread_id, QaThread.user_id == user.id))
    if thread is None:
        raise NotFound("Chat not found")

    attachments = db.scalars(
        select(QaMedia).where(QaMedia.thread_id == thread.id, QaMedia.user_id == user.id)
    ).all()
    file_paths = [Path(item.file_path).resolve() for item in attachments]
    output_dir = (Path(settings.upload_dir) / "generated").resolve()

    db.execute(delete(QaMedia).where(QaMedia.thread_id == thread.id, QaMedia.user_id == user.id))
    db.execute(delete(QaMessage).where(QaMessage.thread_id == thread.id))
    db.delete(thread)
    db.commit()

    # Delete only generated files under the configured media folder.
    for path in file_paths:
        if path.is_relative_to(output_dir):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("qa_media_cleanup_failed thread=%s err=%s", thread_id, str(exc)[:160])
    return Response(status_code=204)


@router.post("/qa/generate-image", response_model=dict)
def qa_generate_image(payload: QaImageGenerateIn, user: CurrentUser, db: DbSession) -> dict:
    if not settings.image_api_key:
        raise UpstreamError("Image generation is not configured for this deployment.")

    if payload.thread_id:
        thread = db.get(QaThread, payload.thread_id)
        if thread is None or thread.user_id != user.id:
            raise NotFound("Thread not found")
    else:
        thread = QaThread(id=f"qa_{uuid.uuid4().hex[:20]}", user_id=user.id, title=payload.prompt[:80])
        db.add(thread)
        db.flush()

    user_message = QaMessage(thread_id=thread.id, role="user", content=payload.prompt)
    db.add(user_message)
    db.flush()

    try:
        response = httpx.post(
            f"{settings.image_api_base_url.rstrip('/')}/images/generations",
            headers={"Authorization": f"Bearer {settings.image_api_key}"},
            json={
                "model": settings.image_generation_model,
                "prompt": payload.prompt,
                "n": 1,
                "size": "1024x1024",
                "quality": "medium",
                "output_format": "png",
                "safety_identifier": hashlib.sha256(user.id.encode("utf-8")).hexdigest(),
            },
            timeout=180,
        )
        response.raise_for_status()
        encoded = response.json()["data"][0]["b64_json"]
        image_bytes = base64.b64decode(encoded, validate=True)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.warning("image_generation_failed user=%s err=%s", user.id, str(exc)[:200])
        raise UpstreamError("Image generation failed. Check the image API configuration and try again.") from exc

    if len(image_bytes) > 20 * 1024 * 1024:
        raise PayloadTooLarge("Generated image exceeds the 20 MB storage limit")

    media_id = f"med_{uuid.uuid4().hex[:20]}"
    output_dir = Path(settings.upload_dir) / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{media_id}.png"
    file_path.write_bytes(image_bytes)

    answer_text = "Generated an engineering illustration from your prompt."
    assistant_message = QaMessage(
        thread_id=thread.id,
        role="assistant",
        content=answer_text,
        citations=[],
        confidence=1.0,
    )
    db.add(assistant_message)
    db.flush()
    attachment = QaMedia(
        id=media_id,
        user_id=user.id,
        thread_id=thread.id,
        message_id=assistant_message.id,
        kind="image",
        mime_type="image/png",
        file_path=str(file_path),
        prompt=payload.prompt,
    )
    db.add(attachment)
    db.flush()
    return {
        "thread_id": thread.id,
        "answer": answer_text,
        "attachment": QaMediaOut(
            id=attachment.id,
            kind="image",
            mime_type=attachment.mime_type,
            url=f"/api/v1/qa/media/{attachment.id}",
            prompt=attachment.prompt,
            created_at=attachment.created_at,
        ),
    }


@router.get("/qa/media/{media_id}")
def qa_media(media_id: str, user: CurrentUser, db: DbSession) -> FileResponse:
    attachment = db.scalar(select(QaMedia).where(QaMedia.id == media_id, QaMedia.user_id == user.id))
    if attachment is None:
        raise NotFound("Media not found")
    path = Path(attachment.file_path).resolve()
    output_dir = (Path(settings.upload_dir) / "generated").resolve()
    if not path.is_relative_to(output_dir) or not path.is_file():
        raise NotFound("Media not found")
    return FileResponse(path, media_type=attachment.mime_type, headers={"Cache-Control": "private, no-store"})


# -------------------------------- Dashboard -------------------------------- #
@router.get("/dashboard", response_model=DashboardStats)
def dashboard(user: CurrentUser, db: DbSession) -> DashboardStats:
    total_plans = db.scalar(
        select(func.count()).select_from(ProcessPlan).where(ProcessPlan.owner_id == user.id)
    ) or 0
    by_status_rows = db.execute(
        select(ProcessPlan.status, func.count()).where(ProcessPlan.owner_id == user.id).group_by(ProcessPlan.status)
    ).all()
    plans_by_status = {s.value if hasattr(s, "value") else str(s): c for s, c in by_status_rows}

    total_inspections = db.scalar(
        select(func.count()).select_from(Inspection).where(Inspection.owner_id == user.id)
    ) or 0
    failed = db.scalar(
        select(func.count())
        .select_from(Inspection)
        .where(Inspection.owner_id == user.id)
        .where(Inspection.result["verdict"].as_string() == "fail")
    ) or 0
    defect_rate = (failed / total_inspections) if total_inspections else 0.0

    avg_rating = db.scalar(select(func.avg(Feedback.rating)).where(Feedback.actor_id == user.id)) or 0.0
    total_documents = db.scalar(
        select(func.count()).select_from(Document).where(Document.created_by.in_(["system", user.id]))
    ) or 0
    total_feedback = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.actor_id == user.id)) or 0

    approvals = db.scalars(
        select(Approval)
        .join(ProcessPlan, Approval.plan_id == ProcessPlan.id)
        .where(ProcessPlan.owner_id == user.id)
        .order_by(Approval.created_at.desc())
        .limit(8)
    ).all()

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
