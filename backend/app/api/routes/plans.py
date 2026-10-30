"""Process plan routes: generate, list, get, decision workflow, approvals."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, EngineerUser
from app.core.errors import NotFound, ValidationFailure
from app.models import Approval, PlanStatus, ProcessPlan
from app.schemas import (
    ApprovalOut,
    ApprovalsOut,
    PlanDecisionIn,
    PlanGenerateIn,
    PlansOut,
    ProcessPlanOut,
)
from app.services.planner import generate_plan

router = APIRouter(prefix="/plans", tags=["planning"])


@router.post("/generate", response_model=ProcessPlanOut, status_code=201)
def generate(payload: PlanGenerateIn, user: EngineerUser, db: DbSession) -> ProcessPlanOut:
    plan = generate_plan(db, user_id=user.id, payload=payload)
    return ProcessPlanOut.model_validate(plan)


@router.get("", response_model=PlansOut)
def list_plans(
    user: CurrentUser,
    db: DbSession,
    status: str = "",
    part_number: str = "",
    limit: int = 50,
    offset: int = 0,
) -> PlansOut:
    from sqlalchemy import func

    query = select(ProcessPlan).where(ProcessPlan.owner_id == user.id).order_by(ProcessPlan.created_at.desc())
    if status:
        query = query.where(ProcessPlan.status == PlanStatus(status))
    if part_number:
        query = query.where(ProcessPlan.part_number.ilike(f"%{part_number}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    plans = db.scalars(query.limit(min(limit, 200)).offset(offset)).all()
    return PlansOut(items=[ProcessPlanOut.model_validate(p) for p in plans], total=total)


@router.get("/{plan_id}", response_model=ProcessPlanOut)
def get_plan(plan_id: str, user: CurrentUser, db: DbSession) -> ProcessPlanOut:
    plan = db.scalar(select(ProcessPlan).where(ProcessPlan.id == plan_id, ProcessPlan.owner_id == user.id))
    if plan is None:
        raise NotFound("Plan not found")
    return ProcessPlanOut.model_validate(plan)


@router.get("/{plan_id}/approvals", response_model=ApprovalsOut)
def get_approvals(plan_id: str, user: CurrentUser, db: DbSession) -> ApprovalsOut:
    plan = db.scalar(select(ProcessPlan).where(ProcessPlan.id == plan_id, ProcessPlan.owner_id == user.id))
    if plan is None:
        raise NotFound("Plan not found")
    approvals = db.scalars(
        select(Approval).where(Approval.plan_id == plan_id).order_by(Approval.created_at.asc())
    ).all()
    return ApprovalsOut(items=[ApprovalOut.model_validate(a) for a in approvals])


@router.post("/{plan_id}/decision", response_model=ProcessPlanOut)
def decide(plan_id: str, payload: PlanDecisionIn, user: EngineerUser, db: DbSession) -> ProcessPlanOut:
    plan = db.scalar(select(ProcessPlan).where(ProcessPlan.id == plan_id, ProcessPlan.owner_id == user.id))
    if plan is None:
        raise NotFound("Plan not found")

    transitions = {
        "submit": {PlanStatus.DRAFT: PlanStatus.SUBMITTED},
        "approve": {PlanStatus.SUBMITTED: PlanStatus.APPROVED},
        "reject": {PlanStatus.SUBMITTED: PlanStatus.REJECTED},
        "revise": {PlanStatus.DRAFT: PlanStatus.DRAFT, PlanStatus.REJECTED: PlanStatus.DRAFT},
    }
    allowed = transitions.get(payload.action, {}).get(plan.status)
    if allowed is None:
        raise ValidationFailure(
            f"Cannot '{payload.action}' a plan in status '{plan.status.value}'",
            details={"current_status": plan.status.value},
        )

    if payload.action == "revise" and payload.revised_plan:
        plan.plan = payload.revised_plan
        plan.version += 1
        # Re-validate edited plans: engineer edits never bypass the rule engine.
        from app.services.rules import validate_plan

        report = validate_plan(payload.revised_plan, plan.requirements)
        plan.validation = report.model_dump(mode="json")

    plan.status = allowed
    if payload.action == "reject" and payload.comment:
        plan.rejected_reason = payload.comment

    db.add(
        Approval(
            id=f"apr_{__import__('uuid').uuid4().hex[:20]}",
            plan_id=plan.id,
            action=payload.action,
            actor_id=user.id,
            actor_name=user.full_name or user.email,
            comment=payload.comment,
            snapshot=plan.plan,
        )
    )
    db.flush()
    return ProcessPlanOut.model_validate(plan)


@router.post("/{plan_id}/duplicate", response_model=ProcessPlanOut, status_code=201)
def duplicate(plan_id: str, user: EngineerUser, db: DbSession) -> ProcessPlanOut:
    """Fork an approved plan as a new draft (continuous-improvement workflow)."""
    plan = db.scalar(select(ProcessPlan).where(ProcessPlan.id == plan_id, ProcessPlan.owner_id == user.id))
    if plan is None:
        raise NotFound("Plan not found")
    copy = ProcessPlan(
        id=f"plan_{__import__('uuid').uuid4().hex[:20]}",
        title=f"{plan.title} (copy)",
        part_number=plan.part_number,
        material=plan.material,
        quantity=plan.quantity,
        requirements=plan.requirements,
        plan=plan.plan,
        status=PlanStatus.DRAFT,
        version=1,
        validation=plan.validation,
        grounding=plan.grounding,
        owner_id=user.id,
    )
    db.add(copy)
    db.flush()
    return ProcessPlanOut.model_validate(copy)
