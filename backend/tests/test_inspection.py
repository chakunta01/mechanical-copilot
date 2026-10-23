"""Inspection pipeline tests: quality gate + FakeLLM analysis + disposition."""

import io

import numpy as np
from PIL import Image


def _jpeg(w: int = 960, h: int = 720, brightness: int = 110, features: bool = True) -> bytes:
    """Synthetic 'part photo': disc with a bright scratch on mid-gray background."""
    import cv2

    img = np.full((h, w, 3), brightness, dtype=np.uint8)
    if features:
        cv2.circle(img, (w // 2, h // 2), min(w, h) // 3, (150, 150, 155), -1)
        cv2.line(img, (w // 3, h // 3), (w // 2, h // 2), (235, 235, 240), 3)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_quality_gate_rejects_dark_image(client, auth_headers, clean_vector_store):
    # Uniformly dark frame: no part visible, mean brightness far below the gate.
    r = client.post(
        "/api/v1/inspections/analyze?part_number=PN-DARK",
        files={"file": ("dark.jpg", _jpeg(brightness=5, features=False), "image/jpeg")},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["quality"]["passed"] is False
    assert body["result"]["verdict"] == "inconclusive"
    assert "quality gate" in body["result"]["explanation"]


def test_quality_gate_rejects_blur(client, auth_headers, clean_vector_store):
    import cv2

    img_bytes = _jpeg()
    arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    blurred = cv2.GaussianBlur(arr, (51, 51), 30)
    ok, buf = cv2.imencode(".jpg", blurred)
    r = client.post(
        "/api/v1/inspections/analyze?part_number=PN-BLUR",
        files={"file": ("blur.jpg", buf.tobytes(), "image/jpeg")},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    sharp = body["quality"]["checks"]["sharpness"]
    assert sharp["passed"] is False


def test_analyze_ok_image_returns_verdict(client, auth_headers, clean_vector_store):
    r = client.post(
        "/api/v1/inspections/analyze?part_number=PN-OK",
        files={"file": ("part.jpg", _jpeg(), "image/jpeg")},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["quality"]["passed"] is True
    assert body["status"] == "analyzed"
    assert body["result"]["verdict"] in ("pass", "fail", "inconclusive")
    assert body["result"]["explanation"], "VLM must explain its verdict"


def test_rejects_non_image(client, auth_headers):
    r = client.post(
        "/api/v1/inspections/analyze",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
        headers=auth_headers,
    )
    assert r.status_code == 415


def test_disposition_flow(client, auth_headers, clean_vector_store):
    r = client.post(
        "/api/v1/inspections/analyze?part_number=PN-DISP",
        files={"file": ("part.jpg", _jpeg(), "image/jpeg")},
        headers=auth_headers,
    )
    insp_id = r.json()["id"]
    r = client.post(
        f"/api/v1/inspections/{insp_id}/disposition",
        json={"disposition": "accept", "notes": "scratch within Class C limit"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["disposition"] == "accept"
    assert body["reviewed_by"]


def test_corrupt_image_handled(client, auth_headers):
    r = client.post(
        "/api/v1/inspections/analyze",
        files={"file": ("bad.jpg", b"\xff\xd8\xff\xe0corruptdata", "image/jpeg")},
        headers=auth_headers,
    )
    assert r.status_code in (400, 415)
