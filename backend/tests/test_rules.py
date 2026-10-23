"""Direct unit tests for the rule engine."""

from app.services.rules import validate_plan


def _plan(ops, inspection_plan=None):
    return {
        "plan_title": "t",
        "operations": ops,
        "inspection_plan": inspection_plan
        if inspection_plan is not None
        else [{"characteristic": "visual", "method": "visual", "frequency": "100%", "acceptance_criteria": "per QS-77"}],
        "assumptions": [],
        "risk_notes": [],
    }


def test_valid_plan_passes():
    report = validate_plan(
        _plan(
            [
                {"op_number": 10, "name": "turn", "machine": "CNC Lathe-1", "tooling": ["CNMG"], "parameters": {"spindle_rpm": 1800}, "inspection_checkpoints": ["OD check"]},
                {"op_number": 20, "name": "mill", "machine": "VMC-2", "tooling": ["end mill"], "parameters": {}, "inspection_checkpoints": ["keyway"]},
            ]
        ),
        {"material": "steel", "quantity": 25},
    )
    assert report.ok, report.errors
    assert report.errors == []


def test_unknown_machine_fails():
    report = validate_plan(
        _plan([{"op_number": 10, "name": "op", "machine": "Magic Machine 9000", "tooling": ["x"]}]),
        {"material": "steel", "quantity": 25},
    )
    assert not report.ok
    assert any(i.rule_id == "MACH_UNKNOWN" for i in report.errors)


def test_forbidden_process_on_machine_fails():
    report = validate_plan(
        _plan([{"op_number": 10, "name": "milling edge", "machine": "CNC Lathe-1", "tooling": ["x"]}]),
        {"material": "steel", "quantity": 25},
    )
    assert not report.ok
    assert any(i.rule_id == "MACH_FORBIDDEN" for i in report.errors)


def test_missing_inspection_plan_fails():
    report = validate_plan(
        _plan([{"op_number": 10, "name": "op", "machine": "VMC-1", "tooling": ["x"]}], inspection_plan=[]),
        {"material": "steel", "quantity": 25},
    )
    assert not report.ok
    assert any(i.rule_id == "STRUCT_INSPECTION_PLAN" for i in report.errors)


def test_low_quantity_requires_visual_inspection():
    report = validate_plan(
        _plan(
            [{"op_number": 10, "name": "op", "machine": "VMC-1", "tooling": ["x"]}],
            inspection_plan=[{"characteristic": "dims", "method": "CMM", "frequency": "FAI", "acceptance_criteria": "drawing"}],
        ),
        {"material": "steel", "quantity": 5},
    )
    assert not report.ok
    assert any(i.rule_id == "QTY_INSPECT" for i in report.errors)


def test_operation_ordering_enforced():
    report = validate_plan(
        _plan(
            [
                {"op_number": 20, "name": "second", "machine": "VMC-1", "tooling": ["x"]},
                {"op_number": 10, "name": "first", "machine": "VMC-2", "tooling": ["y"]},
            ]
        ),
        {"material": "steel", "quantity": 25},
    )
    assert not report.ok
    assert any(i.rule_id == "STRUCT_OP_ORDER" for i in report.errors)


def test_titanium_notes_warning():
    report = validate_plan(
        _plan([{"op_number": 10, "name": "mill", "machine": "VMC-1", "tooling": ["x"]}]),
        {"material": "Ti-6Al-4V titanium", "quantity": 25},
    )
    assert any(i.rule_id == "MAT_NOTE_MISSING" for i in report.warnings)
