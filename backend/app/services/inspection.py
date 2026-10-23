"""Inspection service: image quality gate -> VLM analysis -> verdict with evidence."""

from __future__ import annotations

import base64
import io
import uuid
from typing import Any

import cv2
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import UnsupportedMediaType, ValidationFailure
from app.core.logging import get_logger
from app.models import AuditLog, Inspection, InspectionStatus
from app.schemas import Citation
from app.services import knowledge
from app.services.inspection_schema import GeneratedInspection
from app.services.llm import get_llm

logger = get_logger("inspection")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_DIM = 1600  # downscale before sending to VLM (cost + latency)

SYSTEM_PROMPT = """You are a manufacturing quality inspection engineer analyzing a part image.
Identify defects visible in the image. For each defect, give type, confidence, severity,
location and concrete visual evidence describing what you see. Judge ONLY from the image;
do not assume defects you cannot see. If image quality prevents judgment, set verdict to
"inconclusive". Output ONLY JSON matching the requested schema.

Use EXACTLY these keys (numeric confidence 0.0-1.0):
{"verdict": "pass|fail|inconclusive", "confidence": 0.0-1.0, "defects": [{"defect_type": "...", "confidence": 0.0-1.0, "severity": "low|medium|high|critical", "location": "...", "evidence": "..."}], "explanation": "...", "recommended_disposition": "accept|reject|rework|review"}
All five top-level keys are required."""


# --------------------------------------------------------------------------- #
# Image quality gate
# --------------------------------------------------------------------------- #
def assess_quality(img: np.ndarray) -> dict[str, Any]:
    """Deterministic pre-VLM checks. Returns report dict with `passed` flag."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    brightness = float(gray.mean())
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Glare: fraction of near-saturated pixels.
    glare_ratio = float((gray > 245).sum()) / float(h * w)

    checks = {
        "resolution": {
            "passed": w >= settings.img_min_width and h >= settings.img_min_height,
            "detail": f"{w}x{h} (min {settings.img_min_width}x{settings.img_min_height})",
        },
        "brightness": {
            "passed": settings.img_min_brightness_mean <= brightness <= settings.img_max_brightness_mean,
            "detail": f"mean={brightness:.1f}",
        },
        "sharpness": {
            "passed": laplacian_var >= settings.img_max_blur_laplacian_var,
            "detail": f"laplacian_var={laplacian_var:.1f} (min {settings.img_max_blur_laplacian_var})",
        },
        "glare": {
            "passed": glare_ratio <= settings.img_max_glare_ratio,
            "detail": f"glare_ratio={glare_ratio:.3f} (max {settings.img_max_glare_ratio})",
        },
    }
    passed = all(c["passed"] for c in checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "metrics": {
            "width": w,
            "height": h,
            "brightness_mean": round(brightness, 1),
            "laplacian_var": round(laplacian_var, 1),
            "glare_ratio": round(glare_ratio, 3),
        },
    }


def load_and_preprocess(data: bytes) -> np.ndarray:
    """Decode, validate type, and downscale. Raises on bad input."""
    try:
        pil = Image.open(io.BytesIO(data))
        pil.load()
    except Exception as exc:
        raise UnsupportedMediaType("File is not a readable image") from exc
    if pil.format not in ("JPEG", "PNG", "WEBP"):
        raise UnsupportedMediaType(f"Unsupported image format: {pil.format}")
    arr = np.array(pil.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def make_thumbnail(img: np.ndarray, max_dim: int = 480) -> bytes:
    h, w = img.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValidationFailure("Failed to encode thumbnail")
    return buf.tobytes()


def _b64_png(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValidationFailure("Failed to encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


# --------------------------------------------------------------------------- #
# VLM analysis
# --------------------------------------------------------------------------- #
def _build_vlm_messages(img_b64: str, part_number: str, context: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Part number: {part_number or 'unknown'}\n\nQUALITY CONTEXT:\n{context}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                },
            ],
        },
    ]


def analyze_image(
    db: Session,
    *,
    owner_id: str,
    part_number: str,
    image_bytes: bytes,
    image_path: str,
    thumbnail_path: str,
) -> Inspection:
    img = load_and_preprocess(image_bytes)
    quality = assess_quality(img)

    inspection = Inspection(
        id=f"insp_{uuid.uuid4().hex[:20]}",
        part_number=part_number,
        image_path=image_path,
        thumbnail_path=thumbnail_path,
        status=InspectionStatus.PENDING,
        quality=quality,
        result={},
        owner_id=owner_id,
    )

    # Hard gate: refuse VLM analysis on unusable images (challenge #2 mitigation).
    if not quality["passed"]:
        failed = [k for k, v in quality["checks"].items() if not v["passed"]]
        inspection.status = InspectionStatus.ANALYZED
        inspection.result = {
            "verdict": "inconclusive",
            "confidence": 0.0,
            "defects": [],
            "explanation": (
                f"Image failed the quality gate ({', '.join(failed)}). "
                "Re-capture the image with proper lighting, focus and framing before analysis."
            ),
            "recommended_disposition": "review",
            "references": [],
        }
        db.add(inspection)
        db.flush()
        return inspection

    # Retrieval for context (acceptance criteria from SOPs / standards).
    citations = knowledge.retrieve(
        f"visual inspection acceptance criteria defects {part_number}",
        doc_types=["sop", "standard", "qa"],
        top_k=4,
    )
    context = "\n".join(f"[K{i}] {c['title']}: {c['snippet'][:200]}" for i, c in enumerate(citations, 1))

    llm = get_llm()
    img_resized = _resize_for_vlm(img)
    img_b64 = _b64_png(img_resized)
    messages = _build_vlm_messages(img_b64, part_number, context)

    try:
        generated, raw = llm.complete_json(messages, GeneratedInspection, temperature=0.1, max_tokens=1500)
    except Exception as exc:
        inspection.status = InspectionStatus.FAILED
        inspection.result = {"error": str(exc)[:500]}
        db.add(inspection)
        db.flush()
        logger.warning("vlm_failed insp=%s err=%s", inspection.id, exc)
        return inspection

    result = generated.model_dump(mode="json")
    result["references"] = [
        Citation(**c).model_dump() for c in citations
    ]
    # Threshold: low-confidence defects are kept but marked for human review.
    threshold = settings.defect_confidence_threshold
    for d in result.get("defects", []):
        if d["confidence"] < threshold:
            d["below_threshold"] = True
    inspection.status = InspectionStatus.ANALYZED
    inspection.result = result
    db.add(inspection)
    db.add(
        AuditLog(
            actor_id=owner_id,
            action="inspection.analyzed",
            target_type="inspection",
            target_id=inspection.id,
            detail={"model": raw.model, "verdict": result.get("verdict")},
        )
    )
    db.flush()
    return inspection


def _resize_for_vlm(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    scale = min(1.0, MAX_IMAGE_DIM / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img
