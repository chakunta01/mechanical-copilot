"""Q&A service: grounded engineering answers + ChatGPT-style general chat.

Two answer paths, clearly labeled:

- grounded: retrieval matched the approved knowledge base -> answer ONLY from
  the provided context with [K#] citations (anti-hallucination rules apply).
- general: retrieval found nothing relevant -> answer conversationally from the
  LLM's broad expertise (like Gemini/ChatGPT/Kimi), with no citations, labeled
  `mode="general"`. A hard refusal remains only when no real LLM is available
  (offline FakeLLM) or the LLM call fails.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFound, UpstreamError
from app.core.logging import get_logger
from app.models import QaMessage, QaThread
from app.schemas import QaAnswer
from app.services import knowledge
from app.services.llm import get_llm

logger = get_logger("qa")

SYSTEM_PROMPT = """You are an engineering knowledge assistant for a manufacturing plant.
Answer ONLY from the provided KNOWLEDGE CONTEXT. Rules:
- Cite sources inline as [K1], [K2] matching the context entries you used.
- If the context does not contain the answer, say exactly what is missing and refuse to guess.
- Never invent specifications, standards numbers or procedures.
- Prefer quoting acceptance criteria verbatim with the source reference."""

GENERAL_SYSTEM_PROMPT = """You are Copilot, a friendly expert AI assistant for a manufacturing plant team.
Answer ANY question with clear, accurate, well-structured general knowledge — science, coding, writing,
math, history, health basics, travel, everyday life, and engineering alike.
This question could not be answered from the plant's approved document set, so:
- Do NOT cite sources and do NOT invent SOP numbers, standard numbers or internal procedures.
- If the question concerns THIS plant's internal rules (SOPs, approved machines, acceptance criteria),
  answer from sound general engineering knowledge and end with one short line advising the user to
  verify against the plant's controlled documents.
Be concise and helpful; use short paragraphs or bullet lists where they aid clarity."""

HISTORY_TURNS = 10  # assistant+user messages of conversational memory for general chat


class QaResponseSchema(BaseModel):
    answer: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


def _refuse(
    db: Session,
    thread: QaThread,
    citations: list[dict],
    top_score: float,
    reason: str,
) -> QaAnswer:
    """Honest refusal: no relevant KB content AND no trustworthy way to answer."""
    answer_text = (
        "I could not find relevant information in the approved knowledge base for this question, "
        "and no language model is currently available to answer from general knowledge. "
        "Please check the relevant SOP/standard directly or upload the document to the knowledge base."
    )
    db.add(
        QaMessage(
            thread_id=thread.id,
            role="assistant",
            content=answer_text,
            citations=[],
            confidence=0.0,
        )
    )
    db.flush()
    return QaAnswer(
        thread_id=thread.id,
        answer=answer_text,
        citations=citations,
        confidence=round(top_score, 4),
        refused=True,
        refusal_reason=reason,
    )


def _general_chat(
    db: Session,
    thread: QaThread,
    question: str,
    top_score: float,
) -> QaAnswer:
    """Off-topic for the KB -> broad-expertise conversational answer, labeled `general`."""
    history = (
        db.query(QaMessage)
        .filter(QaMessage.thread_id == thread.id)
        .order_by(QaMessage.id.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    convo: list[dict[str, str]] = [{"role": "system", "content": GENERAL_SYSTEM_PROMPT}]
    for m in reversed(history):
        convo.append({"role": m.role, "content": m.content})

    llm = get_llm()
    try:
        generated, _raw = llm.complete_json(convo, QaResponseSchema, temperature=0.6, max_tokens=1200)
    except UpstreamError as exc:
        logger.warning("general_chat_failed thread=%s err=%s", thread.id, str(exc)[:200])
        return _refuse(db, thread, [], top_score, "llm_unavailable")

    db.add(
        QaMessage(
            thread_id=thread.id,
            role="assistant",
            content=generated.answer,
            citations=[],
            confidence=round(generated.confidence, 4),
        )
    )
    db.flush()
    return QaAnswer(
        thread_id=thread.id,
        answer=generated.answer,
        citations=[],
        confidence=round(generated.confidence, 4),
        refused=False,
        mode="general",
    )


def ask(db: Session, user_id: str, thread_id: str | None, question: str) -> QaAnswer:
    # 1. Thread management.
    if thread_id:
        thread = db.get(QaThread, thread_id)
        if thread is None or thread.user_id != user_id:
            raise NotFound("Thread not found")
    else:
        thread = QaThread(id=f"qa_{uuid.uuid4().hex[:20]}", user_id=user_id, title=question[:80])
        db.add(thread)
        db.flush()

    db.add(QaMessage(thread_id=thread.id, role="user", content=question))
    db.flush()

    # 2. Retrieve.
    citations = knowledge.retrieve(question, top_k=settings.retrieval_top_k)
    top_score = citations[0]["score"] if citations else 0.0

    # Refusal gate (anti-hallucination): the question is not clearly relevant to
    # the corpus — either below the absolute floor, or not clearly above the
    # off-topic baseline. The baseline is measured at runtime with probe
    # questions that are guaranteed irrelevant to manufacturing, embedded with
    # the SAME model, so the gate self-calibrates for any embedding provider.
    baseline = knowledge.off_topic_baseline()
    gate_failed = (
        not citations
        or top_score < settings.qa_refusal_threshold
        or top_score < baseline * settings.qa_baseline_margin
    )
    if gate_failed:
        # ChatGPT-style behavior: answer anyway from broad expertise instead of
        # dead-ending. Hard refusal remains only without a real LLM (offline
        # FakeLLM) or when the LLM call fails — honesty over guessing.
        if get_llm().name == "fake":
            return _refuse(db, thread, citations, top_score, "low_retrieval_confidence")
        return _general_chat(db, thread, question, top_score)

    # 3. Grounded generation.
    context = "\n\n".join(
        f"[K{i}] source: {c['title']} ({c['source_ref']} v{c['version']})\n{c['snippet']}"
        for i, c in enumerate(citations, 1)
    )
    llm = get_llm()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"KNOWLEDGE CONTEXT:\n{context}\n\nQUESTION: {question}\n\nAnswer with citations now.",
        },
    ]
    generated, _raw = llm.complete_json(messages, QaResponseSchema, temperature=0.2, max_tokens=1200)

    db.add(
        QaMessage(
            thread_id=thread.id,
            role="assistant",
            content=generated.answer,
            citations=[dict(c) for c in citations],
            confidence=round(generated.confidence, 4),
        )
    )
    db.flush()
    return QaAnswer(
        thread_id=thread.id,
        answer=generated.answer,
        citations=[dict(c) for c in citations],
        confidence=round(generated.confidence, 4),
        refused=False,
    )
