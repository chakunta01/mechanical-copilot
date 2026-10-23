#!/usr/bin/env python3
"""End-to-end demo: register -> seed KB -> generate plan -> validate -> approve
-> inspect image -> grounded Q&A -> feedback. Run with backend + seed active.

Usage:  python scripts/demo.py [base_url]
Default base_url: http://localhost:8000
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
API = f"{BASE}/api/v1"


def banner(msg: str) -> None:
    print(f"\n{'=' * 70}\n{msg}\n{'=' * 70}")


def main() -> None:
    client = httpx.Client(timeout=120)

    banner("1. Health check")
    r = client.get(f"{BASE}/health")
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))

    banner("2. Register demo engineer")
    email = f"demo_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(f"{API}/auth/register", json={"email": email, "password": "demo-password-123", "full_name": "Demo Engineer"})
    if r.status_code == 409:
        r = client.post(f"{API}/auth/login", json={"email": email, "password": "demo-password-123"})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"Authenticated as {email}")

    banner("3. Generate a grounded process plan")
    plan_req = {
        "requirements": {
            "part_number": "SHF-350-A",
            "material": "C45 steel",
            "quantity": 25,
            "tolerance_notes": "Bearing seats Ø24.00 h6, overall length 50.0 ±0.1 mm",
            "surface_finish": "Ra 0.8 on bearing seats",
            "features": ["6 mm keyway", "4x Ø5 cross holes"],
            "special_requirements": ["material certification"],
        }
    }
    r = client.post(f"{API}/plans/generate", json=plan_req, headers=headers)
    r.raise_for_status()
    plan = r.json()
    print(f"Plan {plan['id']} | status={plan['status']} | validation ok={plan['validation']['ok']}")
    print(f"Grounding: {json.dumps(plan['grounding'], indent=2)}")
    for op in plan["plan"].get("operations", []):
        print(f"  OP{op['op_number']:>3} {op['name']:<28} on {op['machine']}")

    banner("4. Submit and approve the plan (human-in-the-loop)")
    pid = plan["id"]
    r = client.post(f"{API}/plans/{pid}/decision", json={"action": "submit"}, headers=headers)
    r.raise_for_status()
    r = client.post(f"{API}/plans/{pid}/decision", json={"action": "approve", "comment": "Looks good for pilot lot"}, headers=headers)
    r.raise_for_status()
    print(f"Plan status: {r.json()['status']}")

    banner("5. Upload a part image for inspection")
    # Generate a synthetic 'part photo' (gray disc with bright scratch) for demo.
    import io

    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(7)
    img = np.full((720, 960, 3), 90, dtype=np.uint8)
    import cv2

    cv2.circle(img, (480, 360), 260, (150, 150, 155), -1)
    cv2.circle(img, (480, 360), 260, (60, 60, 60), 4)
    cv2.line(img, (350, 250), (430, 300), (230, 230, 235), 3)  # scratch-like mark
    noise = rng.normal(0, 5, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok

    r = client.post(
        f"{API}/inspections/analyze?part_number=SHF-350-A",
        files={"file": ("part_surface.jpg", buf.tobytes(), "image/jpeg")},
        headers=headers,
    )
    r.raise_for_status()
    insp = r.json()
    print(f"Inspection {insp['id']} | verdict={insp['result'].get('verdict')} | quality passed={insp['quality'].get('passed')}")
    for d in insp["result"].get("defects", []):
        print(f"  defect: {d['defect_type']} conf={d['confidence']} sev={d['severity']}")

    banner("6. Grounded Q&A (refuses when KB lacks the answer)")
    r = client.post(f"{API}/qa/ask", json={"question": "What spindle RPM range is approved for roughing steel on a VMC per SOP?"}, headers=headers)
    r.raise_for_status()
    ans = r.json()
    print(f"Q: roughing steel RPM on VMC?\nA: {ans['answer'][:400]}")
    print(f"citations={len(ans['citations'])} refused={ans['refused']}")

    r = client.post(f"{API}/qa/ask", json={"question": "What is the recommended barbecue recipe for the company picnic?"}, headers=headers)
    r.raise_for_status()
    ans2 = r.json()
    print(f"\nQ: barbecue recipe? refused={ans2['refused']} (anti-hallucination gate)")

    banner("7. Engineer feedback (continuous improvement)")
    r = client.post(
        f"{API}/feedback",
        json={"target_type": "plan", "target_id": pid, "rating": 4, "category": "usefulness", "notes": "Good draft; would add deburr op before grinding."},
        headers=headers,
    )
    r.raise_for_status()
    print("Feedback recorded.")

    banner("Demo complete. Open http://localhost:8000/docs for the full API.")


if __name__ == "__main__":
    main()
