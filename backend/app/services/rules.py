"""Deterministic rule engine: validates generated plans against machine, tooling,
material and quality constraints. The LLM proposes; this layer disposes.

Rules live in data/rulepacks/*.yaml so process engineers can tune them without
touching code. The engine also hard-codes structural rules (op numbering,
checkpoint presence) that must always hold.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.core.logging import get_logger
from app.schemas import RuleValidationReport, ValidationIssue

logger = get_logger("rules")

_RULES_DIR = Path(__file__).resolve().parents[3] / "data" / "rulepacks"


def load_rulepack() -> dict[str, Any]:
    """Load and merge all rulepack YAML files (sorted by name)."""
    merged: dict[str, Any] = {"machines": {}, "materials": {}, "hard_rules": {}}
    if not _RULES_DIR.exists():
        return merged
    for path in sorted(_RULES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("bad_rulepack file=%s err=%s", path.name, exc)
            continue
        for key in ("machines", "materials", "hard_rules"):
            if isinstance(data.get(key), dict):
                merged[key].update(data[key])
    return merged


def validate_plan(plan: dict[str, Any], requirements: dict[str, Any]) -> RuleValidationReport:
    """Run all rules against a structured plan. Returns a report; never raises."""
    rules = load_rulepack()
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    operations: list[dict[str, Any]] = plan.get("operations") or []
    if not operations:
        errors.append(
            ValidationIssue(rule_id="STRUCT_NO_OPS", severity="error", message="Plan has no operations", field="operations")
        )
        return RuleValidationReport(ok=False, errors=errors, warnings=warnings)

    machines_db: dict[str, Any] = rules.get("machines", {})
    materials_db: dict[str, Any] = rules.get("materials", {})
    hard: dict[str, Any] = rules.get("hard_rules", {})

    # --- Structural rules --------------------------------------------------- #
    nums = [op.get("op_number") for op in operations]
    if any(not isinstance(n, int) for n in nums):
        errors.append(ValidationIssue(rule_id="STRUCT_OP_NUM", severity="error", message="Operation numbers must be integers", field="operations"))
    elif sorted(nums) != nums or len(set(nums)) != len(nums):
        errors.append(ValidationIssue(rule_id="STRUCT_OP_ORDER", severity="error", message="Operation numbers must be strictly increasing and unique", field="operations"))

    for op in operations:
        name = op.get("name") or "unnamed"
        if not op.get("machine"):
            errors.append(ValidationIssue(rule_id="STRUCT_MACHINE", severity="error", message=f"Operation '{name}' has no machine assigned", field="operations.machine"))
        if not op.get("tooling"):
            warnings.append(ValidationIssue(rule_id="STRUCT_TOOLING", severity="warning", message=f"Operation '{name}' lists no tooling", field="operations.tooling"))
        if not op.get("inspection_checkpoints"):
            warnings.append(ValidationIssue(rule_id="STRUCT_CHECKPOINT", severity="warning", message=f"Operation '{name}' has no inspection checkpoints", field="operations.inspection_checkpoints"))

    if not plan.get("inspection_plan"):
        errors.append(ValidationIssue(rule_id="STRUCT_INSPECTION_PLAN", severity="error", message="Plan is missing the inspection plan section", field="inspection_plan"))

    # --- Machine capability rules ------------------------------------------- #
    for op in operations:
        machine = str(op.get("machine") or "")
        op_name = str(op.get("name") or "")
        # Resolve machine against master data: exact key, then case-insensitive.
        mrule = machines_db.get(machine)
        if mrule is None:
            key = next((k for k in machines_db if k.lower() == machine.lower()), None)
            mrule = machines_db.get(key) if key else None
        if mrule is None and machines_db:
            errors.append(
                ValidationIssue(
                    rule_id="MACH_UNKNOWN",
                    severity="error",
                    message=f"Machine '{machine}' is not in approved machine master data",
                    field="operations.machine",
                )
            )
            continue
        if not mrule:
            continue
        forbidden = mrule.get("forbidden_processes", []) or []
        for proc in forbidden:
            # Word-boundary match, ignoring stock-allowance phrasing such as
            # "+2 mm grinding stock" — that mentions the process word without
            # performing it on this machine.
            pattern = re.compile(rf"\b{re.escape(str(proc).lower())}\b(?!\s+stock)")
            if pattern.search(op_name.lower()):
                errors.append(
                    ValidationIssue(
                        rule_id="MACH_FORBIDDEN",
                        severity="error",
                        message=f"Process '{proc}' is not allowed on {machine}",
                        field="operations.name",
                    )
                )
        max_ops = mrule.get("max_ops_per_plan")
        if isinstance(max_ops, int) and len(operations) > max_ops:
            warnings.append(
                ValidationIssue(
                    rule_id="MACH_MAX_OPS",
                    severity="warning",
                    message=f"{machine} appears in a plan with {len(operations)} ops (max {max_ops})",
                    field="operations",
                )
            )
        allowed_params = mrule.get("allowed_parameters", []) or []
        if allowed_params:
            for param in op.get("parameters") or {}:
                if not any(str(param) == str(a) or str(param).startswith(str(a)) for a in allowed_params):
                    warnings.append(
                        ValidationIssue(
                            rule_id="MACH_PARAM",
                            severity="warning",
                            message=f"Parameter '{param}' on {machine} is not in the approved parameter list",
                            field="operations.parameters",
                        )
                    )

    # --- Material rules ------------------------------------------------------- #
    material = str(requirements.get("material") or "")
    if material:
        mkey = next((k for k in materials_db if k.lower() in material.lower()), None)
        if mkey:
            mrule = materials_db[mkey]
            forbidden_processes = mrule.get("forbidden_processes", [])
            for op in operations:
                op_l = str(op.get("name") or "").lower()
                for proc in forbidden_processes:
                    if proc.lower() in op_l:
                        errors.append(ValidationIssue(rule_id="MAT_FORBIDDEN", severity="error", message=f"Process '{proc}' is not approved for material {mkey}", field="operations.name"))
            notes = mrule.get("required_notes", [])
            for note in notes:
                if note.lower() not in json_lower(plan):
                    warnings.append(ValidationIssue(rule_id="MAT_NOTE_MISSING", severity="warning", message=f"Material {mkey} usually requires note: '{note}'", field="plan"))
        else:
            warnings.append(ValidationIssue(rule_id="MAT_UNKNOWN", severity="warning", message=f"Material '{material}' not in master data; verify certification requirements", field="material"))

    # --- Quantity rules -------------------------------------------------------- #
    qty = int(requirements.get("quantity") or 1)
    qty_break = hard.get("quantity_breaks", [])
    for br in qty_break:
        if br.get("max_qty") is not None and qty <= int(br["max_qty"]) and qty >= int(br.get("min_qty", 1)):
            if br.get("require_full_inspection"):
                visual_items = [i for i in (plan.get("inspection_plan") or []) if "visual" in str(i.get("method", "")).lower()]
                if not visual_items:
                    errors.append(ValidationIssue(rule_id="QTY_INSPECT", severity="error", message="Low-quantity orders require 100% visual inspection in the plan", field="inspection_plan"))

    ok = not errors
    return RuleValidationReport(ok=ok, errors=errors, warnings=warnings)


def json_lower(obj: Any) -> str:
    return str(obj).lower()


def _machine_matches(master_name: str, referenced: str) -> bool:
    m = re.escape(master_name.lower())
    return bool(re.search(rf"\b{m}\b", referenced.lower())) or referenced.lower() in master_name.lower()


# Kept for future fuzzy matching needs; currently unused by validate_plan.
_ = _machine_matches
