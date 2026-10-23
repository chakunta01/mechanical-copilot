"""Planner service: requirements -> grounded structured process plan.

Pipeline:
1. Retrieve supporting knowledge (SOPs, routings, standards, lessons).
2. Ask the LLM for a schema-constrained plan, with retrieved chunks inline.
3. Run the deterministic rule engine; feed errors back for one bounded repair.
4. Enforce grounding: flag plan statements that have no retrieved support.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.models import AuditLog, PlanStatus, ProcessPlan
from app.schemas import (
    Citation,
    GroundingReport,
    PlanGenerateIn,
    RuleValidationReport,
)
from app.services import knowledge
from app.services.llm import get_llm
from app.services.rules import validate_plan
from app.services.plan_schema import GeneratedPlan

logger = get_logger("planner")

SYSTEM_PROMPT = """You are a senior manufacturing process planning engineer.
Generate a draft process plan STRICTLY grounded in the provided KNOWLEDGE CONTEXT.

Rules:
- Every operation must cite the knowledge entries it relies on: put the [K1]-style ids
  INLINE in the operation description text, e.g. "Turn OD to 24.5 mm [K2]".
  MANDATORY: every operation description MUST contain at least one [K#] marker.
- Suggest only machines and tooling that appear in the knowledge context or are standard shop equipment.
- Include inspection checkpoints per operation and a final inspection plan.
- If required information is missing, put it in "assumptions" - never invent specifications silently.
- Output ONLY JSON matching the requested schema. No prose outside JSON."""


def _build_context(citations: list[dict]) -> str:
    """Format retrieved chunks as [K1]...[Kn] blocks for the prompt."""
    lines: list[str] = []
    for i, c in enumerate(citations, 1):
        lines.append(f"[K{i}] source: {c['title']} ({c['source_ref']} v{c['version']})\n{c['snippet']}")
    return "\n\n".join(lines)


def _requirements_text(req: dict[str, Any]) -> str:
    parts = [f"Part: {req.get('part_number')}"]
    if req.get("material"):
        parts.append(f"Material: {req['material']}")
    if req.get("quantity"):
        parts.append(f"Quantity: {req['quantity']}")
    if req.get("tolerance_notes"):
        parts.append(f"Tolerances: {req['tolerance_notes']}")
    if req.get("surface_finish"):
        parts.append(f"Surface finish: {req['surface_finish']}")
    for f in req.get("features") or []:
        parts.append(f"Feature: {f}")
    for s in req.get("special_requirements") or []:
        parts.append(f"Special: {s}")
    if req.get("notes"):
        parts.append(f"Notes: {req['notes']}")
    return "\n".join(parts)


def _citation_key(text: str) -> list[str]:
    """Extract [K1]-style keys mentioned in a text blob."""
    return re.findall(r"\[K(\d+)\]", text)


_STOPWORDS = set(
    "the a an and or of to for with on in by is are be as at from into per plus using use must shall should this that then when while after before each any all not no".split()
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9-]{3,}", text.lower())) - _STOPWORDS


def _attach_heuristic_citations(plan: GeneratedPlan, citations: list[dict]) -> int:
    """Deterministic fallback: attach the best-overlap retrieved chunk to any
    operation the LLM left uncited. Keeps grounding a pipeline guarantee rather
    than a model-compliance hope. Returns number of ops filled."""
    chunk_tokens = [set(_tokens(f"{c['title']} {c['snippet']}")) for c in citations]
    filled = 0
    for op in plan.operations:
        if op.citations:
            continue
        tokens = _tokens(" ".join([op.name, op.description, " ".join(op.inspection_checkpoints)]))
        if not tokens:
            continue
        best_i, best_score = -1, 0.0
        for i, ct in enumerate(chunk_tokens):
            inter = len(tokens & ct)
            score = inter / (min(len(tokens), len(ct)) or 1)
            if score > best_score:
                best_i, best_score = i, score
        if best_i >= 0 and best_score >= 0.15:
            op.citations = [Citation(**citations[best_i])]
            filled += 1
    return filled


def _attach_citations(plan: GeneratedPlan, citations: list[dict]) -> None:
    """Distribute citation objects onto operations that referenced their [Kn] key."""
    total_ops = 0
    for op in plan.operations:
        keys = _citation_key(
            " ".join(
                [op.description]
                + op.inspection_checkpoints
                + list(str(v) for v in op.parameters.values())
            )
        )
        cited: list[Citation] = []
        for k in keys:
            idx = int(k) - 1
            if 0 <= idx < len(citations):
                cited.append(Citation(**citations[idx]))
        op.citations = cited
        if cited:
            total_ops += 1
    return total_ops  # type: ignore[return-value]


def _unsupported_claim_scan(plan: GeneratedPlan, citations: list[dict]) -> list[str]:
    """Flag concrete numeric specs in the plan that no retrieved chunk supports."""
    if not settings.unsupported_claim_guard:
        return []
    corpus = " ".join(c["snippet"].lower() for c in citations)
    flags: list[str] = []
    pattern = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mm|um|µm|rpm|mm/rev|mm/min|deg|°|µm|kN|bar)\b")
    for op in plan.operations:
        blob = " ".join(
            [op.description]
            + [str(v) for v in op.parameters.values()]
            + op.inspection_checkpoints
        ).lower()
        for match in pattern.findall(blob):
            token = f"{match[0]} {match[1]}"
            # Numeric token not present anywhere in the retrieved corpus.
            if match[0] not in corpus and token.split()[0] not in corpus:
                flags.append(f"op{op.op_number}: unverified spec '{token}'")
    return flags[:20]


def generate_plan(db: Session, user_id: str, payload: PlanGenerateIn) -> ProcessPlan:
    req = payload.requirements.model_dump()

    # 1. Retrieve grounding knowledge.
    query = " ".join(
        [
            req.get("part_number", ""),
            req.get("material", ""),
            " ".join(req.get("features") or []),
            " ".join(req.get("special_requirements") or []),
            req.get("tolerance_notes", ""),
            "process planning routing operation sequence",
        ]
    ).strip()
    doc_types = ["sop", "routing", "standard", "lesson"]
    citations = knowledge.retrieve(query, doc_types=doc_types, top_k=settings.retrieval_top_k)
    context = _build_context(citations)

    # 2. Generate with schema-constrained JSON output.
    llm = get_llm()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"REQUIREMENTS:\n{_requirements_text(req)}\n\n"
                f"KNOWLEDGE CONTEXT (cite as [K1]-[K{nlen(citations)}]):\n{context}\n\n"
                "Produce the process plan JSON now."
            ),
        },
    ]
    generated, raw = llm.complete_json(messages, GeneratedPlan, temperature=settings.llm_temperature, max_tokens=3000)

    # 3. Deterministic validation with one bounded repair loop.
    validation = validate_plan(generated.model_dump(), req)
    if not validation.ok:
        repair_msg = {
            "role": "user",
            "content": (
                "The plan failed rule validation. Fix these issues and return the FULL corrected JSON:\n"
                + "\n".join(f"- [{i.rule_id}] {i.message}" for i in validation.errors)
            ),
        }
        try:
            generated, raw = llm.complete_json(
                messages + [repair_msg], GeneratedPlan, temperature=0.1, max_tokens=3000
            )
            validation = validate_plan(generated.model_dump(), req)
        except UpstreamError:
            logger.warning("plan_repair_failed plan kept with validation errors")

    # 4. Grounding report: citations attached + unsupported-claim scan.
    ops_with_cites = _attach_citations(generated, citations)
    if ops_with_cites < len(generated.operations):
        ops_with_cites += _attach_heuristic_citations(generated, citations)
    unsupported = _unsupported_claim_scan(generated, citations)
    grounding = GroundingReport(
        citation_count=len(citations),
        operations_with_citations=ops_with_cites,
        total_operations=len(generated.operations),
        unsupported_claims=unsupported,
    ).model_dump()

    # 5. Persist.
    plan_row = ProcessPlan(
        id=f"plan_{uuid.uuid4().hex[:20]}",
        title=payload.title or generated.plan_title or f"Plan for {req.get('part_number')}",
        part_number=req["part_number"],
        material=req.get("material", ""),
        quantity=req.get("quantity", 1),
        requirements=req,
        plan=generated.model_dump(),
        status=PlanStatus.DRAFT,
        version=1,
        validation=validation.model_dump(mode="json"),
        grounding=grounding,
        owner_id=user_id,
    )
    db.add(plan_row)
    db.flush()

    db.add(
        AuditLog(
            actor_id=user_id,
            action="plan.generated",
            target_type="plan",
            target_id=plan_row.id,
            detail={"model": raw.model, "citations": len(citations), "validation_ok": validation.ok},
        )
    )
    db.flush()
    return plan_row


def nlen(items: list) -> int:
    return len(items)
