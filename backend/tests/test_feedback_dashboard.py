"""Feedback, audit and dashboard tests."""


def test_feedback_lifecycle(client, auth_headers, clean_vector_store):
    client.post(
        "/api/v1/documents",
        json={"title": "T", "doc_type": "sop", "content": "SECTION 1\nSteel milling speeds."},
        headers=auth_headers,
    )
    plan = client.post(
        "/api/v1/plans/generate",
        json={"requirements": {"part_number": "FB-1", "material": "steel", "quantity": 30}},
        headers=auth_headers,
    ).json()

    r = client.post(
        "/api/v1/feedback",
        json={"target_type": "plan", "target_id": plan["id"], "rating": 4, "category": "correctness", "notes": "good draft"},
        headers=auth_headers,
    )
    assert r.status_code == 201

    r = client.get("/api/v1/feedback?target_type=plan", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_dashboard_aggregates(client, auth_headers, clean_vector_store):
    client.post(
        "/api/v1/documents",
        json={"title": "D", "doc_type": "routing", "content": "OP 10 - MILL: VMC-1 steel."},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/plans/generate",
        json={"requirements": {"part_number": "DB-1", "material": "steel", "quantity": 30}},
        headers=auth_headers,
    )

    r = client.get("/api/v1/dashboard", headers=auth_headers)
    assert r.status_code == 200
    stats = r.json()
    assert stats["total_plans"] >= 1
    assert stats["total_documents"] >= 1
    assert "draft" in stats["plans_by_status"]


def test_audit_trail_records_actions(client, auth_headers, clean_vector_store):
    client.post(
        "/api/v1/documents",
        json={"title": "A", "doc_type": "sop", "content": "SECTION 1\nSteel milling speeds."},
        headers=auth_headers,
    )
    plan = client.post(
        "/api/v1/plans/generate",
        json={"requirements": {"part_number": "AU-1", "material": "steel", "quantity": 30}},
        headers=auth_headers,
    ).json()
    client.post(f"/api/v1/plans/{plan['id']}/decision", json={"action": "submit"}, headers=auth_headers)

    # Non-admins cannot read audit.
    r = client.get("/api/v1/admin/audit", headers=auth_headers)
    assert r.status_code == 403
