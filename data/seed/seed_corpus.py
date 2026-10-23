"""Seed the knowledge base with a representative manufacturing corpus.

Run:  python -m data.seed.seed_corpus
Idempotent: documents are matched on (title, version) and skipped if present.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.db import SessionLocal, engine  # noqa: E402
from app.models import Base, Document  # noqa: E402
from app.services import knowledge  # noqa: E402

from sqlalchemy import select  # noqa: E402

CORPUS: list[dict] = [
    {
        "title": "SOP-MILL-001: General Milling Operations",
        "doc_type": "sop",
        "source_ref": "SOP-MILL-001",
        "version": "v2.1",
        "content": """SECTION 1: SCOPE
This SOP covers setup and operation of Vertical Machining Centers (VMC) for milling of steel, aluminum and titanium parts.

SECTION 2: FIXTURING
2.1 Verify fixture torque to 40 Nm before each batch.
2.2 Use V-blocks for round stock; parallel set for rectangular stock.
2.3 Confirm part is seated with 0.02 mm feeler gauge before cycle start.

SECTION 3: CUTTING PARAMETERS - STEEL
3.1 Roughing: spindle 3000-5000 RPM, feed 200-400 mm/min, depth of cut 1.0-2.0 mm.
3.2 Finishing: spindle 6000-8000 RPM, feed 100-250 mm/min, depth of cut 0.2-0.5 mm.
3.3 Flood coolant required for all steel milling.

SECTION 4: CUTTING PARAMETERS - ALUMINUM
4.1 Roughing: spindle 8000-12000 RPM, feed 800-1500 mm/min.
4.2 Finishing: spindle 12000-16000 RPM, feed 500-900 mm/min.
4.3 Mist coolant acceptable; flood preferred for mirror finishes.

SECTION 5: CUTTING PARAMETERS - TITANIUM
5.1 Spindle max 2000 RPM for Ø12 mm carbide tools. Feed 50-120 mm/min.
5.2 Depth of cut max 0.5 mm radial. Continuous flood coolant mandatory.
5.3 Monitor tool wear every 15 minutes; replace insert at 0.3 mm flank wear.

SECTION 6: DEBURRING AND FINISHING
6.1 Deburr all edges after machining; edges must pass shop cloth test.
6.2 Chamfer all through-hole entries 0.3 mm x 45 degrees unless drawing forbids.

SECTION 7: IN-PROCESS INSPECTION
7.1 First article: full dimensional layout per drawing.
7.2 In-process: check critical dimensions every 10 parts with calibrated instruments.
7.3 Surface finish requirement Ra 1.6 or better on sealing faces, measured with profilometer.""",
    },
    {
        "title": "SOP-LATHE-002: Turning Operations - CNC Lathes",
        "doc_type": "sop",
        "source_ref": "SOP-LATHE-002",
        "version": "v1.3",
        "content": """SECTION 1: SCOPE
CNC lathe operation for round parts up to Ø200 mm including facing, OD/ID turning, grooving and threading.

SECTION 2: WORKHOLDING
2.1 3-jaw chuck for stock under Ø80 mm; collet chuck for bar work.
2.2 Max RPM with 3-jaw chuck: 2500 RPM. Collet work max 4000 RPM.
2.3 Tailstock required for parts with L/D ratio greater than 3.

SECTION 3: CUTTING PARAMETERS - STEEL TURNING
3.1 Rough turning: 1600-2200 RPM, feed 0.20-0.30 mm/rev, depth of cut 1.5-2.5 mm.
3.2 Finish turning: 2400-3000 RPM, feed 0.08-0.12 mm/rev, depth of cut 0.2-0.4 mm.
3.3 CNMG or DNMG carbide inserts; replace at 0.3 mm flank wear.

SECTION 4: IN-PROCESS CHECKS
4.1 Check OD with micrometer every 5 parts; log readings on control chart.
4.2 Verify overall length ±0.1 mm on first article and every 10th part.
4.3 Surface finish Ra target 1.6 for machined sealing surfaces; 3.2 elsewhere.

SECTION 5: QUALITY REQUIREMENTS
5.1 Material certification must be verified before first cut of any lot.
5.2 Chip color indicates cutting health: silver chips acceptable, blue chips indicate speed too high or feed too low.""",
    },
    {
        "title": "Routing Sheet Example: Shaft Family RF-100",
        "doc_type": "routing",
        "source_ref": "RT-RF100",
        "version": "v4",
        "content": """ROUTING RF-100: Shaft family, material C45 steel (medium carbon).

OP 10 - SAW: Cut bar stock to 55 mm length, +2 mm grinding stock. Machine: Horizontal bandsaw.
OP 20 - FACE & TURN: CNC Lathe-1. Face both ends to 50.0 ±0.1 mm. Turn OD to Ø24.5 leaving 0.5 mm grind stock. RPM 1800, feed 0.22 mm/rev, coolant flood.
OP 30 - MILL KEYWAY: VMC-2. Mill 6 mm keyway to depth 3.3 +0.2/-0.0 mm using 6 mm carbide end mill at 6000 RPM, feed 250 mm/min. V-block fixture.
OP 40 - DRILL CROSS HOLES: VMC-2. Drill Ø5 through holes, 4x, 90 degrees apart. Peck depth 2 mm.
OP 50 - GRIND: Surface Grinder-1. Grind bearing seats to Ø24.00 h6. Wheel speed 30 m/s.
OP 60 - FINAL INSPECTION: QC Bench. CMM dimensional layout, surface finish Ra 0.8 on bearing seats, visual inspection per QC-VIS-001.""",
    },
    {
        "title": "Quality Standard QS-77: Visual Inspection Acceptance Criteria",
        "doc_type": "standard",
        "source_ref": "QS-77 §3",
        "version": "v3.0",
        "content": """SECTION 1: PURPOSE
Defines visual acceptance criteria for machined parts under 100 mm.

SECTION 2: INSPECTION CONDITIONS
2.1 Illumination: 1000-1500 lux white light at 45 degrees.
2.2 Inspector distance 30-45 cm; inspection time minimum 10 seconds per part.
2.3 Background matte gray.

SECTION 3: ACCEPTANCE CRITERIA
3.1 CRACKS: Any crack, any size = REJECT. No exceptions.
3.2 SCRATCHES: Linear marks on non-sealing surfaces acceptable if depth does not catch fingernail and length under 5 mm. Scratches on sealing faces = REJECT.
3.3 BURRS: Burrs must not exceed 0.1 mm or interfere with assembly function. Burr at hole exit acceptable if removed by hand stone pass.
3.4 CORROSION: Any visible corrosion = REJECT for ferrous parts without coating.
3.5 POROSITY (castings): Pores under 0.5 mm and not on sealing/mating surfaces acceptable, max 3 per 100 mm².
3.6 DISCOLORATION: Heat tint on titanium acceptable if removed by approved etch.

SECTION 4: DEFECT CLASSIFICATION
Class A (critical): cracks, corrosion on functional surface, missing material affecting fit. Always reject.
Class B (major): scratches on sealing faces, burrs over limit, porosity over limit. Reject or rework per engineering disposition.
Class C (minor): cosmetic marks on non-functional surfaces. Accept.

SECTION 5: DISPOSITION
PASS: part meets all Class A/B/C criteria.
REWORK: part can be reworked per documented rework routing only.
REJECT: part fails Class A criteria or rework is not possible.""",
    },
    {
        "title": "Lesson Learned LL-019: Titanium Fire and Tool Wear Prevention",
        "doc_type": "lesson",
        "source_ref": "LL-019",
        "version": "v1",
        "content": """LESSON LL-019 (2024-11): During titanium bracket machining, excessive insert wear caused work hardening and subsequent tool fracture, scrapping 6 parts.

ROOT CAUSE: Insert used 45 minutes beyond wear limit. Flank wear exceeded 0.4 mm, causing rubbing and work-hardened layer.

ACTIONS:
1. Titanium ops must log insert change time; hard limit 15 minutes in-cut per edge.
2. Never let tool rub: if strange noise or chip color change, stop and inspect.
3. Flood coolant must be verified BEFORE cycle start; interrupted coolant caused thermal cycling and insert cracking.
4. Any rework of titanium requires engineering approval due to fire and work-hardening risk.

REFERENCES: SOP-MILL-001 Section 5, Titanium machining training TT-04.""",
    },
    {
        "title": "Control Plan CP-350: Precision Shaft Bearing Seats",
        "doc_type": "qa",
        "source_ref": "CP-350",
        "version": "v2",
        "content": """CONTROL PLAN CP-350 - Shaft bearing seat quality controls.

CHARACTERISTIC 1: Bearing seat diameter Ø24.00 h6 (-0.011/0 mm). Method: CMM, 8 point circle. Frequency: first article + every 5th part. Reaction plan: quarantine lot, notify quality engineer.
CHARACTERISTIC 2: Bearing seat surface finish Ra 0.8 max. Method: profilometer, 4 traces. Frequency: first article + last article.
CHARACTERISTIC 3: Keyway width 6.0 +0.2/-0.0 mm. Method: pin gauge + micrometer over pins. Frequency: every 10th part.
CHARACTERISTIC 4: Visual surface defects. Method: visual per QS-77. Frequency: 100 percent.
CHARACTERISTIC 5: Overall length 50.0 ±0.1 mm. Method: micrometer. Frequency: first article + every 10th part.

NOTE: Any dimensional nonconformance requires NCR before disposition. Do not sort parts without quality engineer approval.""",
    },
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        added = 0
        for item in CORPUS:
            exists = db.scalar(
                select(Document).where(Document.title == item["title"], Document.version == item["version"])
            )
            if exists:
                continue
            doc = Document(
                id=f"doc_{__import__('uuid').uuid4().hex[:20]}",
                title=item["title"],
                doc_type=item["doc_type"],
                source_ref=item["source_ref"],
                version=item["version"],
                file_path="seed",
                created_by="seed",
            )
            db.add(doc)
            db.flush()
            knowledge.ingest_document(db, document=doc, content=item["content"])
            added += 1
        db.commit()
        total = db.query(Document).count()
        print(f"Seeded {added} documents. Knowledge base now has {total} documents.")


if __name__ == "__main__":
    seed()
