"""Knowledge base, retrieval and grounded Q&A tests."""

import json

from app.services.llm import BaseLLM, LLMResponse


class _StubGeneralLLM(BaseLLM):
    """Real-LLM stand-in: returns a general-knowledge answer in schema form."""

    name = "stub"

    def complete(self, messages, *, temperature=None, max_tokens=None, response_format=None):
        del messages, temperature, max_tokens, response_format
        return LLMResponse(
            content=json.dumps(
                {
                    "answer": "Brisket is typically smoked 12-16 hours at about 110 C until it probes tender.",
                    "confidence": 0.7,
                }
            ),
            model="stub-1",
            usage={},
        )


DOC = {
    "title": "Test SOP: Steel Milling Parameters",
    "doc_type": "sop",
    "source_ref": "SOP-TEST-1 §3",
    "version": "v1",
    "content": """SECTION 1: SCOPE
Steel milling on VMC machines.

SECTION 2: PARAMETERS
2.1 Roughing steel: spindle 3000-5000 RPM, feed 200-400 mm/min, depth of cut 1.0-2.0 mm.
2.2 Finishing steel: spindle 6000-8000 RPM, feed 100-250 mm/min.
2.3 Flood coolant required for steel.

SECTION 3: INSPECTION
3.1 Check surface finish Ra 1.6 with profilometer after finishing.""",
}


def test_create_and_search_document(client, auth_headers, clean_vector_store):
    r = client.post("/api/v1/documents", json=DOC, headers=auth_headers)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "ingested"
    assert doc["chunk_count"] >= 1

    r = client.post("/api/v1/documents/search", json={"query": "roughing steel spindle RPM"}, headers=auth_headers)
    assert r.status_code == 200
    chunks = r.json()["chunks"]
    assert chunks, "expected retrieval hit"
    assert chunks[0]["title"] == DOC["title"]
    assert chunks[0]["chunk_id"].startswith("chk_")


def test_delete_document(client, auth_headers, clean_vector_store):
    r = client.post("/api/v1/documents", json=DOC, headers=auth_headers)
    doc_id = r.json()["id"]
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers).status_code == 404


def test_qa_refuses_without_kb(client, auth_headers, clean_vector_store):
    r = client.post("/api/v1/qa/ask", json={"question": "What is the torque spec for the flux capacitor clamp?"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is True
    assert body["refusal_reason"] == "low_retrieval_confidence"


def test_qa_general_chat_when_off_topic(client, auth_headers, clean_vector_store, monkeypatch):
    """With a real LLM available, off-topic questions are answered (labeled general), not refused."""
    from app.services import qa as qa_service

    monkeypatch.setattr(qa_service, "get_llm", lambda: _StubGeneralLLM())
    r = client.post(
        "/api/v1/qa/ask",
        json={"question": "How long do I barbecue a beef brisket?"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["mode"] == "general"
    assert body["citations"] == []
    assert "brisket" in body["answer"].lower()


def test_qa_grounded_answers_are_labeled(client, auth_headers, clean_vector_store):
    client.post("/api/v1/documents", json=DOC, headers=auth_headers)
    r = client.post(
        "/api/v1/qa/ask",
        json={"question": "What spindle RPM range is approved for roughing steel on a VMC?"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "grounded"


def test_qa_answers_from_kb(client, auth_headers, clean_vector_store):
    client.post("/api/v1/documents", json=DOC, headers=auth_headers)
    r = client.post(
        "/api/v1/qa/ask",
        json={"question": "What spindle RPM range is approved for roughing steel on a VMC?"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["citations"], "grounded answer must carry citations"
    assert body["citations"][0]["document_id"].startswith("doc_")
