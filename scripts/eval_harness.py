"""Quantitative evaluation harness (report R1.2 / R1.1 roadmap).

Measures the metrics defined in the project deck against the demo corpus:

1. Retrieval grounding: Recall@k and MRR on golden retrieval cases
   (data/eval/golden_retrieval.json - extend it with real plant cases).
2. Plan grounding: citation coverage across operations and unsupported-claim
   rate for a generated demo plan.
3. Inspection: precision/recall of the defect verdict on labeled images, if
   data/eval/images/defect/*.jpg and data/eval/images/nok/... are provided.
4. Expert rubric: mean 1-5 scores per axis from data/eval/rubric.json.

Runs on an isolated throwaway SQLite DB, so it never touches your dev data.

Usage:
  python scripts/eval_harness.py            # offline: FakeLLM + hashing embeds
  python scripts/eval_harness.py --real     # use configured providers from .env
  python scripts/eval_harness.py --min-recall-at-3 0.8   # gate for CI
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data" / "seed"))

# Always isolate the DB and uploads so the harness never touches dev data.
os.environ["DATABASE_URL"] = "sqlite:///./data/eval_copilot.db"
os.environ["UPLOAD_DIR"] = "./data/eval_uploads"
os.environ["RATE_LIMIT_PER_MIN"] = "1000"

args_parser = argparse.ArgumentParser()
args_parser.add_argument("--real", action="store_true", help="use providers from .env instead of offline fakes")
args_parser.add_argument("--min-recall-at-3", type=float, default=None, help="exit 1 if Recall@3 falls below this")
_args, _ = args_parser.parse_known_args()

if not _args.real:
    os.environ.setdefault("LLM_PROVIDER", "fake")
    os.environ.setdefault("EMBEDDINGS_PROVIDER", "hashing")
    os.environ.setdefault("EMBEDDINGS_DIM", "256")
    os.environ.setdefault("HASHING_DIM", "256")

from sqlalchemy import select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.models import Base, ProcessPlan  # noqa: E402
from app.schemas import PlanGenerateIn  # noqa: E402
from app.services import knowledge, planner  # noqa: E402

REPORT_PATH = ROOT / "data" / "eval" / "last_report.json"


def _hit(source_ref: str, expected: list[str]) -> bool:
    """A citation matches an expected doc if the ref starts with it ("CP-350 v2" -> CP-350)."""
    return any(source_ref.startswith(e) or e in source_ref for e in expected)


# --------------------------------------------------------------------------- #
# 1. Retrieval grounding
# --------------------------------------------------------------------------- #
def eval_retrieval() -> dict:
    golden = json.loads((ROOT / "data" / "eval" / "golden_retrieval.json").read_text(encoding="utf-8"))
    cases = golden["cases"]
    per_k: dict[int, list[float]] = {}
    mrr: list[float] = []
    misses: list[str] = []
    max_k = max(k for c in cases for k in c["ks"])
    for case in cases:
        cits = knowledge.retrieve(case["query"], doc_types=case.get("doc_types"), top_k=max_k)
        refs = [c["source_ref"] for c in cits]
        expected = case["expected_refs"]
        for k in case["ks"]:
            hits = sum(1 for e in expected if any(_hit(r, [e]) for r in refs[:k]))
            per_k.setdefault(k, []).append(hits / len(expected))
        rr = 0.0
        for i, ref in enumerate(refs, 1):
            if _hit(ref, expected):
                rr = 1.0 / i
                break
        mrr.append(rr)
        if rr == 0.0:
            misses.append(case["id"])
    out: dict[str, object] = {"cases": len(cases)}
    for k, vals in sorted(per_k.items()):
        out[f"recall@{k}"] = round(sum(vals) / len(vals), 4) if vals else 0.0
    out["mrr"] = round(sum(mrr) / len(mrr), 4) if mrr else 0.0
    out["zero_hit_cases"] = misses
    return out


# --------------------------------------------------------------------------- #
# 2. Plan grounding (demo part SHF-350-A from scripts/demo.py)
# --------------------------------------------------------------------------- #
DEMO_PLAN = {
    "part_number": "SHF-350-A",
    "material": "C45 steel",
    "quantity": 25,
    "tolerance_notes": "Bearing seats Ø24.00 h6, overall length 50.0 ±0.1 mm",
    "surface_finish": "Ra 0.8 on bearing seats",
    "features": ["6 mm keyway", "4x Ø5 cross holes"],
    "special_requirements": ["material certification"],
}


def eval_plan_grounding() -> dict:
    from app.core.db import SessionLocal
    from app.schemas import PlannerRequirements

    with SessionLocal() as db:
        plan_row = planner.generate_plan(
            db,
            user_id=f"eval_{uuid.uuid4().hex[:8]}",
            payload=PlanGenerateIn(requirements=PlannerRequirements.model_validate(DEMO_PLAN)),
        )
        grounding = plan_row.grounding or {}
        total = int(grounding.get("total_operations") or 0)
        with_c = int(grounding.get("operations_with_citations") or 0)
        unsupported = grounding.get("unsupported_claims") or []
        out = {
            "ops_total": total,
            "citation_coverage": round(with_c / total, 4) if total else 0.0,
            "unsupported_claims": len(unsupported),
            "unsupported_rate_per_op": round(len(unsupported) / total, 4) if total else 0.0,
            "validation_ok": bool((plan_row.validation or {}).get("ok")),
        }
    db.commit()
    return out


# --------------------------------------------------------------------------- #
# 3. Inspection precision/recall (only when labeled images are present)
# --------------------------------------------------------------------------- #
def eval_inspection() -> dict | None:
    img_root = ROOT / "data" / "eval" / "images"
    if not img_root.exists():
        return None
    from app.core.db import SessionLocal
    from app.services import inspection as inspection_service

    labeled: list[tuple[bool, Path]] = []
    for truth, folder in ((True, "defect"), (False, "ok")):
        sub = img_root / folder
        if sub.exists():
            labeled += [
                (truth, p)
                for p in sorted(sub.iterdir())
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
            ]
    if not labeled:
        return None

    tp = fp = tn = fn = gates = failures = 0
    with SessionLocal() as db:
        for truth, path in labeled:
            try:
                insp = inspection_service.analyze_image(
                    db,
                    owner_id="eval",
                    part_number="EVAL",
                    image_bytes=path.read_bytes(),
                    image_path=str(path),
                    thumbnail_path="",
                )
            except Exception:
                failures += 1
                continue
            result = insp.result or {}
            if not result:
                gates += 1  # rejected by the image quality gate
                continue
            verdict = str(result.get("verdict", "")).lower()
            predicted_defect = verdict in ("fail",)
            if truth and predicted_defect:
                tp += 1
            elif truth and not predicted_defect:
                fn += 1
            elif not truth and predicted_defect:
                fp += 1
            else:
                tn += 1
        db.commit()
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "images": len(labeled),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "quality_gate_rejected": gates,
        "analysis_failures": failures,
    }


# --------------------------------------------------------------------------- #
# 4. Expert rubric (data/eval/rubric.json)
# --------------------------------------------------------------------------- #
def eval_rubric() -> dict | None:
    path = ROOT / "data" / "eval" / "rubric.json"
    if not path.exists():
        return None
    entries = json.loads(path.read_text(encoding="utf-8"))
    axes: dict[str, list[float]] = {}
    for entry in entries:
        scores = (entry.get("scores") or {}) if isinstance(entry, dict) else {}
        for axis, value in scores.items():
            axes.setdefault(axis, []).append(float(value))
    if not axes:
        return None
    return {
        axis: round(sum(vals) / len(vals), 2) for axis, vals in sorted(axes.items())
    } | {"entries": len(entries)}


def _report_block(label: str, data: dict | None) -> str:
    if data is None:
        return f"{label}: SKIPPED (input data not provided)"
    lines = [f"{label}:"]
    for key, value in data.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> None:
    eval_dir = ROOT / "data" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Fresh throwaway DB + corpus seeding.
    db_file = engine.url.database
    if db_file and Path(db_file).exists():
        Path(db_file).unlink()
    Base.metadata.create_all(bind=engine)
    import seed_corpus  # noqa: E402

    seed_corpus.seed()

    retrieval = eval_retrieval()
    plan_pkg = eval_plan_grounding()
    inspection = eval_inspection()
    rubric = eval_rubric()

    report = {
        "retrieval": retrieval,
        "plan_grounding": plan_pkg,
        "inspection": inspection,
        "expert_rubric": rubric,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 70)
    print("EVALUATION REPORT (Mechanical Copilot)")
    print("=" * 70)
    print(_report_block("Retrieval grounding", retrieval))
    print(_report_block("Plan grounding", plan_pkg))
    print(_report_block("Inspection P/R", inspection))
    print(_report_block("Expert rubric", rubric))
    print(f"\nJSON report written to {REPORT_PATH}")

    if args.min_recall_at_3 is not None:
        got = float(retrieval.get("recall@3", 0.0))
        if got < args.min_recall_at_3:
            print(f"FAILED: recall@3 {got} < required {args.min_recall_at_3}")
            raise SystemExit(1)
        print(f"PASSED: recall@3 {got} >= required {args.min_recall_at_3}")


if __name__ == "__main__":
    run(_args)
