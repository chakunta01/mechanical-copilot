"""Inspection routes: upload image, analyze, list, get, disposition."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, EngineerUser
from app.core.config import settings
from app.core.errors import NotFound, PayloadTooLarge, UnsupportedMediaType
from app.models import AuditLog, Inspection, InspectionStatus
from app.schemas import DispositionIn, InspectionOut, InspectionsOut
from app.services.inspection import ALLOWED_TYPES, analyze_image

router = APIRouter(prefix="/inspections", tags=["inspection"])


@router.post("/analyze", response_model=InspectionOut, status_code=201)
async def analyze(
    file: UploadFile,
    user: EngineerUser,
    db: DbSession,
    part_number: str = "",
) -> InspectionOut:
    if file.content_type not in ALLOWED_TYPES:
        raise UnsupportedMediaType(f"Allowed: {', '.join(sorted(ALLOWED_TYPES))}")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise PayloadTooLarge(f"Max {settings.max_upload_mb} MB")

    insp_id = f"insp_{uuid.uuid4().hex[:20]}"
    upload_dir = Path(settings.upload_dir) / "inspections"
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"{insp_id}.jpg"
    image_path.write_bytes(data)

    # Thumbnail written by the service after decode.
    thumbnail_path = upload_dir / f"{insp_id}_thumb.jpg"

    inspection = analyze_image(
        db,
        owner_id=user.id,
        part_number=part_number,
        image_bytes=data,
        image_path=str(image_path),
        thumbnail_path=str(thumbnail_path),
    )
    return InspectionOut.model_validate(inspection)


@router.get("", response_model=InspectionsOut)
def list_inspections(
    user: CurrentUser,
    db: DbSession,
    part_number: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> InspectionsOut:
    query = select(Inspection).where(Inspection.owner_id == user.id).order_by(Inspection.created_at.desc())
    if part_number:
        query = query.where(Inspection.part_number.ilike(f"%{part_number}%"))
    if status:
        query = query.where(Inspection.status == InspectionStatus(status))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.limit(min(limit, 200)).offset(offset)).all()
    return InspectionsOut(items=[InspectionOut.model_validate(i) for i in items], total=total)


@router.get("/{inspection_id}", response_model=InspectionOut)
def get_inspection(inspection_id: str, user: CurrentUser, db: DbSession) -> InspectionOut:
    inspection = db.scalar(select(Inspection).where(Inspection.id == inspection_id, Inspection.owner_id == user.id))
    if inspection is None:
        raise NotFound("Inspection not found")
    return InspectionOut.model_validate(inspection)


@router.get("/{inspection_id}/image")
def get_inspection_image(inspection_id: str, user: CurrentUser, db: DbSession) -> FileResponse:
    inspection = db.scalar(select(Inspection).where(Inspection.id == inspection_id, Inspection.owner_id == user.id))
    if inspection is None:
        raise NotFound("Inspection not found")
    path = Path(inspection.image_path).resolve()
    upload_root = Path(settings.upload_dir).resolve()
    if not path.is_relative_to(upload_root) or not path.is_file():
        raise NotFound("Inspection image not found")
    with Image.open(path) as image:
        media_type = Image.MIME.get(image.format or "", "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/{inspection_id}/disposition", response_model=InspectionOut)
def set_disposition(
    inspection_id: str,
    payload: DispositionIn,
    user: EngineerUser,
    db: DbSession,
) -> InspectionOut:
    inspection = db.scalar(select(Inspection).where(Inspection.id == inspection_id, Inspection.owner_id == user.id))
    if inspection is None:
        raise NotFound("Inspection not found")
    inspection.disposition = payload.disposition
    inspection.reviewed_by = user.full_name or user.email
    inspection.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(
        AuditLog(
            actor_id=user.id,
            action="inspection.disposition",
            target_type="inspection",
            target_id=inspection.id,
            detail={"disposition": payload.disposition, "notes": payload.notes[:200]},
        )
    )
    db.flush()
    return InspectionOut.model_validate(inspection)
