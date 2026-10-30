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

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFound, UpstreamError
from app.core.logging import get_logger
from app.models import QaMessage, QaThread
from app.schemas import Citation, QaAnswer
from app.services import knowledge
from app.services.llm import get_llm

logger = get_logger("qa")

ADAPTIVE_RESPONSE_GUIDE = """Response style:
- Fulfill the user's actual request and requested deliverable directly. Skip greetings, filler, and generic offers to help.
- Keep ordinary answers brief: answer directly in 2–4 sentences or a short list. Expand only when the user explicitly asks for detail.
- Do not append unsolicited offers, follow-up questions, or extra sections. Include them only when needed to resolve a material ambiguity or when the user asks.
- If the user explicitly requests a process plan, or accepts the process-plan offer, provide a concise numbered list of 4–7 actionable steps. Include only essential inputs and checks; do not use a long report template or ask again.
- For any request phrased as steps or a workflow (including CAD modeling), give at most 5 concise, actionable numbered steps. Avoid repeating units, software names, or generic advice in every step. If exact geometry is unspecified, give a useful parametric workflow and name the key dimensions needed for a fully dimensioned model.
- Relevance check: identify the requested subject and deliverable before drafting. Answer that request first; remove material that does not help answer it. If the request lacks inputs needed for a sound result, say exactly what is missing and give only the useful method or a focused question—never fill gaps with invented values.
- For follow-up requests, resolve references such as "it", "that motor", or "those specs" from the conversation. Treat the newest request as the deliverable, reuse earlier specifications as inputs, and do not repeat the previous answer instead of doing the requested task.
- For questions asking for types, modes, stages, components, or another finite list, include every standard item in that category. Keep each item concise instead of omitting items to fit a short response.
- For a topic overview (including one selected from the topic list), use focused headings for **Subtopics**, **Basic definitions**, **Most-used formulas**, and **Constants and units**. Cover the major sub-areas of the selected topic; define every formula symbol and state assumptions/limits; include verified numeric values with SI units only for established constants actually used. Label material properties and process coefficients as context-dependent instead of presenting them as universal constants. Finish the requested sections rather than stopping halfway; omit unrelated applications and filler.
- Choose the structure to fit the task: explain concepts clearly; show inputs, assumptions, equations, substitutions, units, and a sanity check for calculations; use a comparison table for competing options; give ranked causes, diagnostic checks, and corrective actions for troubleshooting; and produce requested writing, code, lists, or plans in the requested form.
- For engineering calculations, never substitute unrelated quantities into a formula. Start from the governing physical model, check dimensional consistency, and state when the supplied inputs are insufficient for a numerical result. For estimates, show the assumptions and a compact worked example.
- For thermal transients, use an energy balance: Q = m c_p ΔT only when the energy absorbed by the part is known. For repeated braking, start with ΔE_vehicle = ½ M(v_i² − v_f²); estimate heat into one rotor as Q_rotor = β ΔE_vehicle, where β is the stated fraction reaching that rotor; then use ΔT = Q_rotor/(m_rotor c_p) for an insulated single stop. For repeated stops, include cooling between stops (for a lumped-capacitance estimate, τ = m_rotor c_p/(hA)). Define every symbol and assumption. Do not multiply force, time, and specific heat capacity.
- For a thermodynamics and power-cycles overview, give a complete concise map: first-law energy balance and second-law/entropy direction, then distinguish ideal air-standard cycles (Otto and Diesel/Dual for reciprocating engines) from gas-turbine Brayton and steam Rankine cycles. State each cycle's heat-addition/rejection process and a valid efficiency/work relation when relevant. Do not imply Otto and Diesel are the only power cycles. Define assumptions and symbols; do not stop mid-cycle or mid-list.
- For air-standard Otto and Diesel cycles, do not invent heat-transfer equations: use the established efficiency relations below and identify r as compression ratio and γ = c_p/c_v. Otto: η = 1 − 1/r^(γ−1). Diesel: η = 1 − [(r_c^γ − 1)/(γ(r_c − 1)r^(γ−1))], where r_c = V_3/V_2 is the cutoff ratio. Derive or qualify other relations instead of guessing.
- For spindle speed, use n = 1000 V_c/(πD) rpm when V_c is in m/min and D is in mm; use n = V_c/(πD) when both are in m. Convert units explicitly and check dimensional consistency before giving a numeric result.
- When a formula uses a named physical constant and its value is requested or materially useful, give the verified numerical value and SI units beside the symbol. Distinguish universal constants from material properties and operating inputs; never invent a numeric value for a variable such as h, k, or ε.
- Before returning a technical answer, silently check: (1) it addresses the exact question, (2) each equation is dimensionally consistent, (3) numerical values follow from stated inputs, (4) units and assumptions are explicit, and (5) uncertainty or safety limits are not hidden. If any check fails, correct the answer or state what cannot be established.
- Present polished, usable output: a direct answer first, descriptive headings only where helpful, consistent SI units, readable equations, and a brief conclusion or next step when the task needs one.
- Do not force headings, tables, examples, or a plan template onto a simple question. Use them when they improve the requested answer.
- Address every part of multi-part requests. When details are missing, make and label a reasonable assumption if that still gives a useful answer; ask one focused clarification only when proceeding would likely mislead.
- Keep answers specific to the user's stated goal and constraints. Separate facts, assumptions, and recommendations. Never invent sources, standard clauses, test results, exact specifications, or internal procedures.

"""

MECHANICAL_DOMAIN_GUIDE = """Mechanical engineering coverage includes:
- Fundamentals: engineering mathematics and units; statics, dynamics, kinematics, mechanics of materials, elasticity, plasticity, stress/strain, buckling, and failure analysis.
- Design: machine elements, mechanisms, shafts, gears, bearings, springs, fasteners, seals, tolerances, GD&T, design optimization, DFM/DFA, and product development.
- Materials: material selection, metallurgy, heat treatment, composites, polymers, corrosion, wear, fatigue, fracture, tribology, and lubrication.
- CAD/CAE/CAM: parametric and direct 3D modeling, assemblies, drawings, CNC programming, machining toolpaths, FEA, CFD, thermal and multibody simulation, and engineering software/code.
- Manufacturing: machining, casting, forming, welding/joining, additive manufacturing, metrology, inspection, quality, automation, and process planning.
- Thermal/fluid/energy: thermodynamics, cycles, heat transfer, fluid mechanics, turbomachinery, combustion, engines, HVAC/refrigeration, power systems, and renewables.
- Mobility and systems: automotive/EV/hybrid powertrains, batteries, vehicle dynamics, braking, suspension, robotics, mechatronics, sensors, actuators, and controls.
- Verification: vibration/noise, testing, instrumentation, reliability, maintenance, root-cause analysis, safety, and engineering documentation.
- Advanced and cross-cutting areas: numerical methods, optimization, computational mechanics, acoustics, biomechanics, micro/nanoscale systems, sustainable design, life-cycle assessment, engineering economics, and systems engineering where relevant to a mechanical task.
- Thermodynamics and energy systems: energy/entropy balances, property tables, exergy, psychrometrics, combustion, internal-combustion cycles (Otto, Diesel, Dual), gas-turbine Brayton, steam Rankine, Carnot limits, refrigeration and heat-pump cycles, boilers, condensers, turbines, compressors, pumps, and heat exchangers.
- Fluids and thermal sciences: hydrostatics, internal/external flow, boundary layers, dimensional analysis, convection correlations, conduction networks, radiation exchange, turbomachinery, HVAC, refrigeration, and CFD assumptions/validation.
- Applied mechanics and product design: statics, dynamics, mechanisms, continuum/solid mechanics, fatigue/fracture, vibration, machine elements, gears, bearings, brakes, shafts, joints, seals, tolerances, and design for manufacture/assembly.
- Production and digital engineering: process selection, CNC/CAM, additive manufacturing, metrology, quality systems, robotics/PLC automation, digital twins, FEA/CFD, uncertainty, verification, and validation.

Handle the requested task type: concepts, comparisons, derivations, worked calculations, design choices, code/scripts,
CAD/CAM instructions, simulation setup, troubleshooting, experiments, reports, and step-by-step workflows. Use SI units
by default. Draw on general engineering knowledge even when the approved document set has no match; reserve citations
and claims of approval for information actually present in that document set. No model knows literally every fact:
state uncertainty, request missing inputs, and flag version-specific, current, standards-based, or safety-critical details
for verification instead of inventing them. Never fabricate equations, material properties, standards clauses, simulation
results, or machine settings.

"""

SYSTEM_PROMPT = ADAPTIVE_RESPONSE_GUIDE + MECHANICAL_DOMAIN_GUIDE + """You are Mechanical Copilot, an expert mechanical engineering assistant with strong practical and theoretical knowledge.
You cover mechanical design, materials, mechanics, machine design, CAD/FEA, GD&T, metrology, manufacturing,
machining, welding, quality, maintenance, HVAC, fluid mechanics, thermodynamics, heat transfer, power systems,
automotive and automobile engineering, engines, EVs, vehicle dynamics, controls, robotics, and autonomous vehicles.

CAD/CAE expertise: guide users through parametric 3D part and assembly design in SolidWorks and Fusion 360,
including design intent, reference planes/axes, fully constrained sketches, dimensions, feature order, patterns,
fillets, configurations/components, drawings, tolerances, and export formats. When requested, produce a clear,
feature-by-feature modeling recipe or a starter macro/script (such as a SolidWorks API or Fusion 360 script),
stating the software/API assumptions and asking for dimensions only when they are needed to make the model precise.
CAD/CAM coverage also includes Inventor, CATIA, NX, Creo, FreeCAD, Onshape, Mastercam, and other common workflows:
direct and parametric modeling, sheet metal, weldments, surfaces, assemblies, drawing release, model repair, and
neutral-file exchange. Help with 2.5D/3-axis/3+2/5-axis milling, turning and mill-turn toolpaths; setup planning;
stock, work coordinate systems, fixtures, tool and holder selection; feeds/speeds; toolpath simulation; and post-
processor/G-code troubleshooting. Calculate cutting data only from supplied material, cutter, machine, and process
inputs or clearly labeled assumptions. Controller dialects and software versions vary; never invent a safe feed,
speed, toolpath clearance, post-processor behavior, or G/M-code for an unspecified machine.
For simulation, cover ANSYS Mechanical/Fluent and Abaqus Standard/Explicit workflows: choose the right analysis,
idealize geometry, assign material data, define contacts, loads and boundary conditions, select element types,
build a suitable mesh, check convergence and energy balance, interpret the requested outputs, and validate against
hand calculations or test data. Explain units and assumptions; never invent a solver result, software command name,
material property, or safety factor. UI labels and options vary by software version, so distinguish stable concepts
from version-specific clicks. A simulation result is only as reliable as its inputs, mesh, and validation.

Answer conceptual and general engineering questions using established engineering knowledge, even when the supplied
KNOWLEDGE CONTEXT does not contain the answer. Explain assumptions, units, reasoning, and practical implications;
show equations or worked steps when useful. Ask a focused clarification only when needed to avoid a misleading answer.
Use SI units by default and identify any assumptions or uncertainty. Never fabricate test results, exact specifications,
standard clauses, or plant procedures. For safety-critical design or maintenance decisions, explain the relevant risks
and say what must be verified before implementation.

When the user asks for a process plan, return a brief numbered step-by-step plan, normally 4–7 steps. Include the
essential machine/tooling and quality checks where relevant, and label uncertain or plant-specific settings for
verification. Do not present a draft as an approved procedure.

Use the KNOWLEDGE CONTEXT as the authority for this plant's internal requirements, approved settings, SOPs, and
acceptance criteria. Cite context-derived claims inline as [K1], [K2]. If context is insufficient for a plant-specific
answer, state what is missing and distinguish general engineering guidance from plant approval. Do not attach a citation
to a claim the cited context does not support."""

GENERAL_SYSTEM_PROMPT = ADAPTIVE_RESPONSE_GUIDE + MECHANICAL_DOMAIN_GUIDE + """You are Mechanical Copilot, a highly capable mechanical engineering expert and practical problem-solving partner.
Your specialties include mechanical design, materials, mechanics, machine elements, CAD/CAE/FEA, GD&T, metrology,
manufacturing processes, CNC machining, joining, quality, reliability, maintenance, thermodynamics, heat transfer,
fluid mechanics, HVAC, energy systems, automotive and automobile engineering, ICE and electric powertrains, batteries,
vehicle dynamics, controls, robotics, and autonomous vehicles. You can also answer other general questions clearly.

For CAD, give practical, feature-by-feature workflows for parametric parts and assemblies in SolidWorks and Fusion
360; include sketch references and constraints, dimensions, design intent, feature sequence, assemblies/joints,
drawings, tolerances, and useful export formats. If asked, write starter SolidWorks API or Fusion 360 scripts, with
the expected software/API version made clear. Also help with Inventor, CATIA, NX, Creo, FreeCAD, Onshape, and
model exchange/repair. For CAM, cover 2.5D/3-axis/3+2/5-axis milling, turning and mill-turn, stock/WCS/fixturing,
cutting-tool and holder selection, operation order, toolpaths, feeds and speeds, simulation, post-processors, and
controller-specific G/M-code troubleshooting. Ask for material, cutter, machine/controller, and setup when needed;
label assumptions and never invent safe cutting parameters or machine-specific codes. For CAE, help set up and interpret ANSYS Mechanical/Fluent and Abaqus
Standard/Explicit analyses. Explain geometry idealization, material properties, contacts, loads, constraints,
element/mesh choices, convergence, result interpretation, and validation against hand calculations or test data.
State units and assumptions, request missing dimensions or boundary conditions when necessary, and do not invent
solver results, exact UI labels, material values, or safety claims. Software menus vary by version; explain the
underlying workflow when exact version details are unknown.
For a conceptual V-engine CAD request, propose a parameter skeleton (bank angle, bore, stroke, cylinder pitch,
deck height, crank throw, and connecting-rod length), model the block, crankshaft, rods, pistons, heads, valvetrain,
and manifolds as separate components, then assemble around crank/cylinder axes and check clearances and motion.
Do not invent engine dimensions; label a dimension-light model conceptual and ask for target dimensions/software
only when a production-accurate design is requested.

This question was not answerable from the approved plant document set. Answer it directly using established knowledge.
Explain the engineering reasoning, assumptions, units, and practical tradeoffs; give formulas or examples when useful.
Use SI units by default. If a key input is missing, state a reasonable assumption or ask one focused question. Be clear
about uncertainty and never invent specifications, standard clauses, test results, or internal procedures.
For safety-critical applications, explain what needs validation before use.

For process-plan requests, give a concise numbered list of 4–7 actionable steps with essential tooling and checks.
Mark uncertain values and plant-specific settings for verification; label the plan as a draft.

Do not cite sources or imply that general guidance is plant-approved. If the user asks about this plant's SOPs, approved
machines, settings, or acceptance criteria, explain what general engineering can say and advise checking the controlled
documents. Keep answers focused and use short sections or bullets when they improve clarity."""

CAD_CAE_SYSTEM_PROMPT = ADAPTIVE_RESPONSE_GUIDE + MECHANICAL_DOMAIN_GUIDE + """You are Mechanical Copilot, a practical CAD/CAM/CAE specialist for mechanical engineering.
Output plain answer text only; do not return JSON or a separate confidence field. Answer the exact request directly.
For requests for steps or a workflow, use 4–6 short numbered steps; do not pad
with repeated or generic instructions.

CAD: support SolidWorks, Fusion 360, Inventor, CATIA, NX, Creo, FreeCAD, Onshape, and common neutral formats.
Explain parametric/direct modeling, reference geometry, fully constrained sketches, design intent, feature trees,
patterns, configurations, assemblies/mates, sheet metal, weldments, surfaces, drawings, GD&T, model repair, and
CAD macros/scripts when requested. Note version differences; do not invent menu labels or exact API behavior.

CAM: support 2.5D/3-axis/3+2/5-axis milling, turning, mill-turn, setup planning, stock/WCS/fixtures, tools and
holders, operation sequencing, toolpaths, cutting data, simulation, post-processors, and G/M-code troubleshooting.
For feeds/speeds, derive values from stated work material, cutter, teeth, machine limits, and engagement; identify
assumptions and ask for missing safety-critical inputs. Never claim a posted program is safe for an unspecified
machine/controller. Include simulation, clearance, prove-out, and dry-run checks where relevant.

For V8 engine CAD, define a master layout (bank angle, bore, stroke, cylinder pitch, deck height, crank throw,
rod length), model the block, crankshaft, rods, pistons, heads, valvetrain, and manifolds separately, then assemble
and check clearances/motion. Give a useful conceptual workflow without invented dimensions; ask for the target
specifications only when a dimensioned design is requested.

For ANSYS Mechanical/Fluent and Abaqus Standard/Explicit, identify the suitable analysis, idealize geometry, assign
verified material data, define contacts, loads and boundary conditions, select elements and mesh, check convergence,
interpret results, and validate against hand calculations or test data. Distinguish stable concepts from software-
version-specific menu labels. Never invent solver results, material properties, or safety claims."""

HISTORY_TURNS = 10  # assistant+user messages of conversational memory for general chat

_DETAILED_ANSWER_CUES = (
    "detailed", "in detail", "comprehensive", "deep dive", "full report",
    "complete guide", "derive", "derivation", "work through", "show all steps",
    "calculate", "numerical", "compare in depth", "write a complete",
    "key ideas", "key concepts", "include equations", "equations", "assumptions", "si units",
    "topic overview", "subtopics", "basic definitions", "most-used formulas", "constants",
)

_PROCESS_PLAN_CUES = (
    "process plan", "step-by-step plan", "step by step plan", "manufacturing plan",
    "plan the process", "make a plan", "create a plan", "give me a plan",
)
_PLAN_ACCEPTANCE = re.compile(
    r"^\s*(?:yes|yeah|yep|sure|please|go ahead|do that|make one|give me one|"
    r"okay|ok|sounds good|i do)(?:\b|[,.!])",
    re.IGNORECASE,
)


def _answer_is_plan(question: str) -> bool:
    normalized = question.casefold()
    return any(cue in normalized for cue in _PROCESS_PLAN_CUES)


def _is_cad_cae_question(question: str) -> bool:
    return bool(
        re.search(
            r"\b(solidworks|solid works|fusion\s*360|ansys|abaqus|finite element|fea|cad|cae|cam|cnc|"
            r"mastercam|solidcam|hyper.?mill|power.?mill|featurecam|inventor|catia|freecad|onshape|creo|"
            r"toolpath|post.?processor|g.?code|m.?code|feeds? and speeds?|cutting data|machin\w*|turning|milling|"
            r"mesh convergence|3d model|3d cad|parametric model|simulation)\b",
            question,
            re.IGNORECASE,
        )
    )


def _answer_token_budget(question: str) -> int:
    """Keep ordinary answers and requested process plans concise."""
    normalized = question.casefold()
    if _answer_is_plan(question):
        return 520
    if re.search(r"\b(steps?|workflow|how to design|how do i design|modeling process)\b", normalized):
        return 520
    if re.search(r"\b(types?|modes?|stages?|components?|list|enumerate|name all|what are the)\b", normalized):
        return 480
    return 1400 if any(cue in normalized for cue in _DETAILED_ANSWER_CUES) else 360


def _completion_is_incomplete(response: Any) -> bool:
    finish_reason = str(
        response.finish_reason
        or response.usage.get("finish_reason", "")
        or response.usage.get("done_reason", "")
    ).casefold()
    if finish_reason in {"length", "max_tokens", "max_output_tokens", "incomplete"}:
        return True
    content = response.content.rstrip()
    if not content:
        return False
    if content.count(r"\(") > content.count(r"\)") or content.count(r"\[") > content.count(r"\]"):
        return True
    return bool(
        re.search(
            r"\b(?:the|a|an|of|and|or|to|with|for|by|from|in|at|is|are|was|were|"
            r"that|which|such as|as|where|when|because|however|into|per|its|their)$",
            content.casefold(),
        )
    )


def _canonical_short_answer(question: str) -> str | None:
    """Return a concise, exact answer for small canonical engineering lists."""
    normalized = re.sub(r"\s+", " ", question.casefold()).strip()
    asks_for_modes = re.match(r"^(?:what are|list|name|give me|identify)\b", normalized)
    asks_about_heat_modes = re.search(r"\bmodes?\b.{0,30}\bheat transfer\b|\bheat transfer\b.{0,30}\bmodes?\b", normalized)
    asks_for_analysis = re.search(
        r"\b(detailed|in detail|derive|derivation|compare|examples?|applications?|"
        r"explain|describe|discuss|calculate|mechanism|difference|why|how)\b",
        normalized,
    )
    if asks_for_modes and asks_about_heat_modes and not asks_for_analysis:
        return (
            "Heat transfers by exactly three modes:\n\n"
            "1. **Conduction:** energy moves through microscopic interactions within a material or between bodies in contact.\n\n"
            "2. **Convection:** energy is carried by the bulk motion of a fluid, together with heat conduction at its surface.\n\n"
            "3. **Radiation:** energy is carried by electromagnetic waves and does not require a material medium. "
            "Its emitted power is **P = εσATₛ⁴** (for a blackbody, ε = 1), where "
            "**σ = 5.670374419 × 10⁻⁸ W·m⁻²·K⁻⁴** (Stefan–Boltzmann constant), "
            "A is area in m² and Tₛ is absolute temperature in K. For a sphere, A = 4πr²."
        )
    asks_yes_no_radiation_mode = (
        re.search(r"\bradiation\b", normalized)
        and re.search(r"\bmode\b.{0,30}\bheat transfer\b|\bheat transfer\b.{0,30}\bmode\b", normalized)
        and re.match(r"^(?:is|does|do|can|would|will)\b", normalized)
    )
    if asks_yes_no_radiation_mode and not asks_for_analysis:
        return (
            "Yes. Radiation is one of the three modes of heat transfer, alongside conduction and convection. "
            "It transfers energy by electromagnetic waves and does not require a material medium. "
            "Total emitted power from a gray surface is P = εσATₛ⁴ (for a blackbody, ε = 1), "
            "where σ = 5.670374419 × 10⁻⁸ W·m⁻²·K⁻⁴ (Stefan–Boltzmann constant), "
            "A is area in m², and Tₛ is absolute temperature in K. For a sphere A = 4πr², "
            "so the sphere's radius-squared term must be included."
        )
    return None


def _canonical_power_cycles_overview(question: str) -> str | None:
    """Give a complete, checked overview for the broad topic-chip prompt."""
    normalized = question.casefold()
    asks_for_overview = re.search(r"\b(help me with|overview|key ideas|key concepts|explain)\b", normalized)
    includes_thermodynamics = re.search(r"\bthermodynamics?\b", normalized)
    includes_power_cycles = re.search(r"\bpower cycles?\b", normalized)
    asks_for_calculation_or_comparison = re.search(r"\b(calculate|numerical|compare|derive|work out)\b", normalized)
    if not (asks_for_overview and includes_thermodynamics and includes_power_cycles) or asks_for_calculation_or_comparison:
        return None
    return (
        "## Subtopics\n\n"
        "Energy and entropy balances; properties and state diagrams; ideal and real cycles; reciprocating engines; "
        "gas turbines; steam plants; cycle efficiency and performance; and cycle modifications such as reheat and regeneration.\n\n"
        "## Basic definitions\n\n"
        "- **System/state:** the matter or region being analyzed and its thermodynamic condition, described by properties such as p, T, and v.\n"
        "- **Heat (Q):** energy transferred because of a temperature difference. **Work (W):** energy transfer by other means.\n"
        "- **Internal energy (u):** microscopic stored energy per unit mass. **Enthalpy (h):** h = u + pv, useful in flowing devices.\n"
        "- **Entropy (s):** property used to track energy dispersal and irreversibility; entropy generation is nonnegative.\n"
        "- **Power cycle:** a sequence returning the working fluid to its initial state while producing net work. "
        "Thermal efficiency is net work divided by heat supplied.\n\n"
        "## Most-used formulas and cycles\n\n"
        "With heat into and work out of a closed system positive, the first law is Q − W = ΔU + ΔKE + ΔPE. "
        "For a complete cycle, the net change in stored energy is zero, so W_net = Q_in − Q_out and "
        "η_th = W_net/Q_in = 1 − Q_out/Q_in.\n\n"
        "1. **Carnot:** reversible reference cycle between two reservoirs; η_Carnot = 1 − T_cold/T_hot. "
        "T_hot and T_cold must be absolute temperatures in K.\n\n"
        "2. **Otto (spark-ignition engines):** isentropic compression → constant-volume heat addition → isentropic "
        "expansion → constant-volume heat rejection. Ideal air-standard efficiency: "
        "\\(\\eta_{Otto} = 1 - 1/r^{\\gamma-1}\\).\n\n"
        "3. **Diesel (compression-ignition engines):** isentropic compression → constant-pressure heat addition → "
        "isentropic expansion → constant-volume heat rejection. Ideal air-standard efficiency: "
        "\\(\\eta_{Diesel} = 1 - \\frac{r_c^{\\gamma} - 1}{\\gamma(r_c - 1)r^{\\gamma-1}}\\).\n\n"
        "4. **Dual:** piston-engine model with heat added partly at constant volume and partly at constant pressure; "
        "compression/expansion are idealized as isentropic. It bridges Otto and Diesel models.\n\n"
        "5. **Brayton (gas turbines):** isentropic compression → constant-pressure heat addition → isentropic "
        "expansion → constant-pressure heat rejection. For an ideal gas with constant specific heats: "
        "\\(\\eta_{Brayton} = 1 - \\frac{1}{r_p^{(\\gamma-1)/\\gamma}}\\).\n\n"
        "6. **Rankine (steam plants):** pump liquid → boiler heat addition → turbine expansion → condenser heat "
        "rejection. Per unit mass: \\(\\eta_{Rankine} = \\frac{(h_3-h_4)-(h_2-h_1)}{h_3-h_2}\\). "
        "States 1–4 are condenser outlet, pump outlet, boiler outlet, and turbine outlet; use steam tables for h.\n\n"
        "## Constants, assumptions, and SI units\n\n"
        "For cold-air-standard calculations, γ = c_p/c_v ≈ 1.4 (dimensionless); it varies with temperature and gas "
        "composition, so use appropriate properties when accuracy matters. For dry air, R ≈ 287 J/(kg·K) in p = ρRT; "
        "it is a specific gas constant, not universal. The ideal-cycle formulas assume ideal-gas air, constant specific "
        "heats where stated, and internally reversible compression/expansion. They are not real-engine predictions. "
        "Use T in K, p in Pa, v in m³/kg, Q and W in J (or specific q and w in J/kg), h and u in J/kg, and efficiencies as fractions. "
        "Real systems need measured boundary conditions, component losses, pressure drops, and validated property data."
    )


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
    if settings.llm_provider == "openai" and not settings.llm_api_key:
        answer_text = (
            "OpenAI is selected, but the server has no OPENAI_API_KEY configured yet. "
            "Add an API key to the server environment and restart Mechanical Copilot to enable answers."
        )
    elif reason == "llm_unavailable":
        if settings.llm_provider == "openai_compatible":
            answer_text = (
                f"The configured local model ({settings.llm_model}) could not be reached. "
                "Check that Ollama is running and the model is installed, then try again."
            )
        else:
            answer_text = (
                "The configured language model could not be reached. Check the server's provider credentials "
                "and network access, then try again."
            )
    else:
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
        citations=[Citation.model_validate(c) for c in citations],
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
    previous_user_question = next((m.content for m in reversed(history) if m.role == "user"), "")
    is_cad_cae_chat = _is_cad_cae_question(question) or _is_cad_cae_question(previous_user_question)
    system_prompt = CAD_CAE_SYSTEM_PROMPT if is_cad_cae_chat else GENERAL_SYSTEM_PROMPT
    convo: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in reversed(history):
        convo.append({"role": m.role, "content": m.content})

    llm = get_llm()
    try:
        # Free-form Q&A does not need schema-constrained JSON. Local Ollama models
        # can fail JSON-schema validation despite returning useful text, which was
        # previously misreported to users as a model connectivity failure.
        raw = llm.complete(
            convo,
            temperature=0.4,
            max_tokens=_answer_token_budget(question),
        )
        answer_text = raw.content.strip()
        if not answer_text:
            raise UpstreamError("The configured language model returned an empty answer")
        for _ in range(2):
            if not _completion_is_incomplete(raw):
                break
            raw = llm.complete(
                convo + [
                    {"role": "assistant", "content": answer_text},
                    {
                        "role": "user",
                        "content": (
                            "Continue from the exact point where the previous answer stopped. "
                            "Finish every part of the original request, complete any unfinished list item or equation, "
                            "and do not repeat the material already answered."
                        ),
                    },
                ],
                temperature=0.3,
                max_tokens=700,
            )
            continuation = raw.content.strip()
            if not continuation:
                break
            answer_text = f"{answer_text.rstrip()}\n{continuation}"
    except UpstreamError as exc:
        logger.warning("general_chat_failed thread=%s err=%s", thread.id, str(exc)[:200])
        return _refuse(db, thread, [], top_score, "llm_unavailable")

    db.add(
        QaMessage(
            thread_id=thread.id,
            role="assistant",
            content=answer_text,
            citations=[],
            confidence=0.65,
        )
    )
    db.flush()
    return QaAnswer(
        thread_id=thread.id,
        answer=answer_text,
        citations=[],
        confidence=0.65,
        refused=False,
        mode="general",
    )


def ask(db: Session, user_id: str, thread_id: str | None, question: str) -> QaAnswer:
    # 1. Thread management.
    if thread_id:
        thread = db.get(QaThread, thread_id)
        if thread is None or thread.user_id != user_id:
            raise NotFound("Thread not found")
        last_message = (
            db.query(QaMessage)
            .filter(QaMessage.thread_id == thread.id)
            .order_by(QaMessage.id.desc())
            .first()
        )
        previous_question = (
            db.query(QaMessage.content)
            .filter(QaMessage.thread_id == thread.id, QaMessage.role == "user")
            .order_by(QaMessage.id.desc())
            .first()
        )
        conversation_history = (
            db.query(QaMessage)
            .filter(QaMessage.thread_id == thread.id)
            .order_by(QaMessage.id.desc())
            .limit(HISTORY_TURNS)
            .all()
        )
        conversation_history.reverse()
    else:
        thread = QaThread(id=f"qa_{uuid.uuid4().hex[:20]}", user_id=user_id, title=question[:80])
        db.add(thread)
        db.flush()
        last_message = None
        previous_question = None
        conversation_history = []

    previous_question_text = previous_question[0] if previous_question else None
    accepts_plan_offer = (
        previous_question_text is not None
        and last_message is not None
        and last_message.role == "assistant"
        and "process plan" in last_message.content.casefold()
        and _PLAN_ACCEPTANCE.match(question) is not None
    )
    answer_question = (
        f"Provide a brief step-by-step process plan for this previous request: {previous_question_text}"
        if accepts_plan_offer
        else question
    )

    db.add(QaMessage(thread_id=thread.id, role="user", content=question))
    db.flush()

    # Persist the prompt before retrieval or model calls. These can take seconds
    # or minutes; keeping the initial SQLite write transaction open for that
    # whole time blocks sign-in, registration, and other chat writes.
    db.commit()

    canonical_answer = _canonical_short_answer(answer_question)
    if canonical_answer is None:
        canonical_answer = _canonical_power_cycles_overview(answer_question)
    if canonical_answer is not None:
        db.add(
            QaMessage(
                thread_id=thread.id,
                role="assistant",
                content=canonical_answer,
                citations=[],
                confidence=1.0,
            )
        )
        db.flush()
        return QaAnswer(
            thread_id=thread.id,
            answer=canonical_answer,
            citations=[],
            confidence=1.0,
            refused=False,
            mode="general",
        )

    # 2. Retrieve.
    citations = knowledge.retrieve(answer_question, top_k=settings.retrieval_top_k, user_id=user_id)
    top_score = citations[0]["score"] if citations else 0.0

    # Most general questions either have no retrieved chunks or already fall
    # below the absolute floor. Skip the extra five-probe embedding call in
    # those common cases; the calibrated baseline is only needed for an
    # otherwise-promising knowledge-base match.
    gate_failed = not citations or top_score < settings.qa_refusal_threshold
    if not gate_failed:
        baseline = knowledge.off_topic_baseline(user_id=user_id)
        gate_failed = top_score < baseline * settings.qa_baseline_margin
    if gate_failed:
        # ChatGPT-style behavior: answer anyway from broad expertise instead of
        # dead-ending. Hard refusal remains only without a real LLM (offline
        # FakeLLM) or when the LLM call fails — honesty over guessing.
        if get_llm().name == "fake":
            return _refuse(db, thread, citations, top_score, "low_retrieval_confidence")
        return _general_chat(db, thread, answer_question, top_score)

    # 3. Grounded generation.
    context = "\n\n".join(
        f"[K{i}] source: {c['title']} ({c['source_ref']} v{c['version']})\n{c['snippet']}"
        for i, c in enumerate(citations, 1)
    )
    llm = get_llm()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(
        {"role": message.role, "content": message.content}
        for message in conversation_history
        if message.role in {"user", "assistant"}
    )
    messages.append(
        {
            "role": "user",
            "content": (
                f"KNOWLEDGE CONTEXT:\n{context}\n\n"
                f"LATEST REQUEST: {answer_question}\n\n"
                "Use prior conversation only as context for references such as 'it' or 'that motor'. "
                "Answer the latest request and requested deliverable directly. If the user asks how to make, fit, "
                "or select a coupler based on earlier motor details, give the coupler procedure and use those details "
                "as inputs; do not repeat the motor specifications as the answer. Do not treat prior assistant text "
                "as a replacement for the latest request. Cite knowledge-context claims inline as [K#]."
            ),
        }
    )
    generated, _raw = llm.complete_json(
        messages,
        QaResponseSchema,
        temperature=0.2,
        max_tokens=_answer_token_budget(question),
    )

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
        citations=[Citation.model_validate(c) for c in citations],
        confidence=round(generated.confidence, 4),
        refused=False,
    )
