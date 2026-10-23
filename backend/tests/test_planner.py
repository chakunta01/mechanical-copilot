"""Planner + approval workflow tests (offline FakeLLM + hashing embeddings)."""

PLAN_REQ = {
    "requirements": {
        "part_number": "SHF-TEST-1",
        "material": "C45 steel",
        "quantity": 25,
        "features": ["6 mm keyway"],
        "special_requirements": ["material certification"],
    }
}


def _seed_kb(client, headers):
    client.post(
        "/api/v1/documents",
        json={
            "title": "Seed Routing for shafts",
            "doc_type": "routing",
            "source_ref": "RT-TEST",
            "version": "v1",
            "content": """ROUTING RT-TEST for shaft parts, material C45 steel.

OP 10 - SAW: Cut bar stock to length. Machine: Horizontal bandsaw.
OP 20 - FACE AND TURN: CNC Lathe-1, face to 50.0 plus/minus 0.1 mm, turn OD to 24.5. RPM 1800 feed 0.22 mm/rev coolant flood.
OP 30 - MILL KEYWAY: VMC-2, 6 mm keyway, 6 mm carbide end mill, RPM 6000, feed 250 mm/min, V-block fixture.
OP 40 - FINAL INSPECTION: QC Bench, CMM layout, visual inspection per QS-77.""",
        },
        headers=headers,
    )


def test_generate_plan_grounded_and_validated(client, auth_headers, clean_vector_store):
    _seed_kb(client, auth_headers)
    r = client.post("/api/v1/plans/generate", json=PLAN_REQ, headers=auth_headers)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["status"] == "draft"
    assert plan["part_number"] == "SHF-TEST-1"
    assert plan["plan"]["operations"], "plan must have operations"
    assert plan["validation"]["ok"] is True, plan["validation"]
    assert plan["grounding"]["citation_count"] >= 1

    ops = plan["plan"]["operations"]
    assert ops[0]["machine"], "every op needs a machine"


def test_plan_workflow_transitions(client, auth_headers, clean_vector_store):
    _seed_kb(client, auth_headers)
    plan = client.post("/api/v1/plans/generate", json=PLAN_REQ, headers=auth_headers).json()
    pid = plan["id"]

    # Cannot approve a draft directly.
    r = client.post(f"/api/v1/plans/{pid}/decision", json={"action": "approve"}, headers=auth_headers)
    assert r.status_code == 400

    assert client.post(f"/api/v1/plans/{pid}/decision", json={"action": "submit"}, headers=auth_headers).status_code == 200
    r = client.post(
        f"/api/v1/plans/{pid}/decision", json={"action": "approve", "comment": "ok for pilot"}, headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Approval trail recorded.
    r = client.get(f"/api/v1/plans/{pid}/approvals", headers=auth_headers)
    actions = [a["action"] for a in r.json()["items"]]
    assert actions == ["submit", "approve"]


def test_rejection_records_reason(client, auth_headers, clean_vector_store):
    _seed_kb(client, auth_headers)
    plan = client.post("/api/v1/plans/generate", json=PLAN_REQ, headers=auth_headers).json()
    pid = plan["id"]
    client.post(f"/api/v1/plans/{pid}/decision", json={"action": "submit"}, headers=auth_headers)
    r = client.post(
        f"/api/v1/plans/{pid}/decision", json={"action": "reject", "comment": "grind stock missing"}, headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["rejected_reason"] == "grind stock missing"

    # Revise brings it back to draft.
    r = client.post(f"/api/v1/plans/{pid}/decision", json={"action": "revise"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_duplicate_creates_draft(client, auth_headers, clean_vector_store):
    _seed_kb(client, auth_headers)
    plan = client.post("/api/v1/plans/generate", json=PLAN_REQ, headers=auth_headers).json()
    pid = plan["id"]
    client.post(f"/api/v1/plans/{pid}/decision", json={"action": "submit"}, headers=auth_headers)
    client.post(f"/api/v1/plans/{pid}/decision", json={"action": "approve"}, headers=auth_headers)

    r = client.post(f"/api/v1/plans/{pid}/duplicate", headers=auth_headers)
    assert r.status_code == 201
    copy = r.json()
    assert copy["status"] == "draft"
    assert copy["id"] != pid
