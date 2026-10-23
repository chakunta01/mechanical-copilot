# Handoff — What's Done & What's Needed From You

## Update — 23 October 2026 (after project report)

The improvement roadmap in `project_report.pdf` was executed. What changed:

| Report item | Status |
|---|---|
| R1.1 Git + CI | ✅ Repo initialized (`main`, 3 commits), fixed `.gitignore` (kept `data/seed` + `data/rulepacks` in VCS; ignores logs, runtime DBs/uploads, `tools/`, `backend/.reportlab_tmp/`, `.freebuff/`), added [.github/workflows/ci.yml](../.github/workflows/ci.yml) (ruff, mypy, pytest, frontend typecheck+build). Note: commit author email is a placeholder `shubhamchakunta@users.noreply.github.com` (repo-local config) — change with `git config user.email` before pushing to GitHub. |
| R1.1 Quality sweep | ✅ ruff 0 errors (was 38), mypy 0 errors on `app` (was: crashed on numpy stubs — `python_version` moved to 3.12; 23 pre-existing type errors found and fixed once it could actually check). One real latent bug fixed: `NameError` on undefined `Citation` in `knowledge.citation_of`. `LLMGateway.complete_json` is now generic over the schema type, so callers get correctly typed models. pytest re-verified: 31/31, exit 0. |
| R1.2 Evaluation harness | ✅ `python scripts/eval_harness.py` (backend venv) — measures Recall@k / MRR on `data/eval/golden_retrieval.json` (8 demo-corpus cases), plan citation coverage + unsupported-claim rate on the SHA‑F‑350 demo part, plus optional inspection P/R (`data/eval/images/{defect,ok}/*.jpg`) and expert rubric (`data/eval/rubric.json`). Runs on a throwaway SQLite DB; writes `data/eval/last_report.json`; `--min-recall-at-3 X` turns it into a CI gate. First baseline (offline hashing embeddings): Recall@1 0.75, MRR 0.875, plan citation coverage 0.25 (FakeLLM), unsupported claims 0. |
| R2.1 Prod compose validation | ⛔ Blocker: Docker is not available in this workspace (`docker: command not found`), so `docker-compose.prod.yml` remains unexecuted. Needs a real Docker host to run once: set `SECRET_KEY` + `POSTGRES_PASSWORD`, `docker compose -f docker-compose.prod.yml up --build -d`, then run `scripts/e2e_verify.sh http://localhost:8080`. |
| LLM path decision (next step 4) | ❓ Open — user decision. Current: portable Ollama `qwen2.5vl:3b` (zero credits). Alternatives in the report: cloud key with credits, or larger local model (`qwen2.5vl:7b`) if VRAM allows. |

Still needed from you (unchanged items below, plus these):
- 10–20 labeled inspection images → `data/eval/images/defect/` and `data/eval/images/ok/` (harness auto-detects them and reports precision/recall).
- 2–3 expert-reviewed plans → `data/eval/rubric.json` (format: `[ {"id": "...", "scores": {"correctness": 5, "grounding": 4, "usefulness": 4, "safety": 5}} ]`).

## Original status: everything runs today, offline, with zero API keys

| Component | State |
|---|---|
| Backend API (FastAPI, 30+ endpoints) | ✅ running on http://localhost:8000 (docs at `/docs`) |
| Frontend (React + TS) | ✅ running on http://localhost:5173 |
| Backend test suite | ✅ 31/31 passing (`cd backend && .venv\Scripts\python -m pytest`) |
| Frontend typecheck + prod build | ✅ clean (`npm run build`) |
| Knowledge base | ✅ seeded with 6 demo documents (2 SOPs, routing, standard, lesson, control plan) |
| Demo plan / inspection / Q&A | ✅ verified end-to-end in the browser |
| Concepts guide (learning PDF) | ✅ [concepts_guide.pdf](concepts_guide.pdf) (compile: `tectonic concepts_guide.tex`) |
| Production deployment files | ✅ Dockerfiles + compose (dev & prod), untested here — needs Docker |

**Demo login:** `admin@example.com` / `copilot-demo-123`

## What I need from you (in priority order)

### 1. An LLM API key — the only thing between demo and real AI
Currently `LLM_PROVIDER=fake` (deterministic canned responses). Any OpenAI-compatible
endpoint works. Put in `.env` (copy from `.env.example`) and restart the backend:

```ini
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1        # or Azure / vLLM / Ollama / LM Studio
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_VISION_MODEL=gpt-4o-mini                  # must accept images

EMBEDDINGS_PROVIDER=openai_compatible
EMBEDDINGS_API_KEY=sk-...
EMBEDDINGS_MODEL=text-embedding-3-small
EMBEDDINGS_DIM=1536
```

Then restart the backend — startup automatically re-embeds every ingested document
with the configured embedding model (no re-seed needed; the seeder skips existing docs).
If the embeddings API is unreachable at boot, the app falls back to offline hashing
embeddings and logs the error instead of crashing.

**Zero-cost local option (Ollama — verified path, no credits needed):**

```bash
ollama pull qwen2.5vl:3b        # one model for chat AND vision (runs on 4 GB GPU)
ollama pull nomic-embed-text    # real embeddings, 768-dim
```

Then in `.env`:

```ini
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5vl:3b
LLM_VISION_MODEL=qwen2.5vl:3b

EMBEDDINGS_PROVIDER=openai_compatible
EMBEDDINGS_BASE_URL=http://localhost:11434/v1
EMBEDDINGS_API_KEY=ollama
EMBEDDINGS_MODEL=nomic-embed-text
EMBEDDINGS_DIM=768
```

Restart the backend. Any OpenAI-compatible endpoint works the same way
(OpenAI / Azure / vLLM / LM Studio / Ollama). If winget is slow, Ollama also ships
a portable zip (extract, run `ollama serve`) — no installer required.

### 2. Your real plant knowledge (makes it *your* copilot)
Replace/augment the demo corpus via the Knowledge Base page (paste text or upload
.txt/.md/.pdf/.docx):
- SOPs and work instructions (per machine/process)
- Routing sheets for representative part families
- Quality standards / visual acceptance criteria
- Control plans
- Lessons learned / NCR summaries
- Machine master data → also update `data/rulepacks/shop_rules.yaml`

### 3. If you want production deployment
- A server with Docker + `SECRET_KEY` and `POSTGRES_PASSWORD` set →
  `docker compose -f docker-compose.prod.yml up --build -d`
- A domain + TLS (nginx config or cloud load balancer)
- Decisions: SSO integration? Audit retention period? Backup policy for Postgres + uploads?

### 4. For evaluation (per the presentation's metrics plan)
- A handful of labeled inspection images (defect / no-defect) to measure precision/recall
- A senior engineer to score 5–10 generated plans against the 1–5 rubric
- (Optional) historical routing sheets to measure planning-time saved

## Known limitations (by design, for now)
- VLM quality is only as good as the model behind it; thresholds in `.env` need
  tuning on your real images (challenge #5 in the deck).
- Rate limiter is in-memory — swap to Redis when running multiple replicas.
- Vector index rebuilds at startup (fine ≤ ~50k chunks; switch `VECTOR_STORE=chroma` beyond).

## Local LLM (Ollama) — active setup
- The OpenAI key had zero credits, so all real inference runs on the local
  portable Ollama in `tools/ollama/` (models: `qwen2.5vl:3b` chat+vision,
  `nomic-embed-text` embeddings). Start order: Ollama → backend → frontend
  (commands below). Backend `/health` should show both providers as
  `openai_compatible`.

```bash
cd tools/ollama && (OLLAMA_CONTEXT_LENGTH=6144 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=30m ./ollama.exe serve > ../../ollama.log 2>&1 &)
cd backend && (./.venv/Scripts/python.exe run.py > ../backend.log 2>&1 &)
```

## Q&A modes: grounded vs general (ChatGPT-style)
- **Grounded** (`mode: "grounded"`): retrieval matched the approved KB — answer
  comes ONLY from the retrieved chunks, with [K#] citations and confidence.
- **General** (`mode: "general"`): question matched nothing in the KB — the
  copilot now answers conversationally from the model's broad expertise (like
  Gemini/ChatGPT/Kimi), no citations, and the UI labels it "General knowledge —
  not from your documents". Thread history (last 10 turns) is included so
  follow-ups keep context.
- A hard refusal (`refused: true`) now happens only when no real LLM is
  available (offline FakeLLM in tests) or the LLM call fails (`llm_unavailable`)
  — honesty over guessing. The self-calibrating off-topic baseline gate in
  `knowledge.off_topic_baseline()` decides which path a question takes.

## Reliability fixes that made local models production-usable
- LLM gateway (`services/llm.py`): Ollama **structured outputs** (`response_format:
  json_schema`) enforce schema-valid JSON at decode time; falls back gracefully
  on endpoints that reject it. Multimodal schema hints append a text part
  instead of string-mangling the image message. JSON extractor unwraps wrapper
  objects/arrays; bounded self-repair loop feeds pydantic errors back.
- Lenient schemas: `references`/`tooling`/`checkpoints` coerce dict-elements to
  strings; inspection accepts `type`→`defect_type`, `"High"`→0.9, severity
  aliases (see `inspection_schema.py`).
- Planner: deterministic citation-attachment fallback (keyword overlap between
  each operation and retrieved chunks) so every operation carries a citation
  even when the small model skips [K#] markers; rulepack gained `Horizontal
  Bandsaw` and the forbidden-process detector ignores "… grinding stock"
  allowance phrasing (`services/rules.py`).
- One-command verification: `bash scripts/e2e_verify.sh` — login, plan (201,
  validation ok, grounded ops), grounded Q&A, off-topic → general chat, VLM
  inspection (quality gate → verdict). All five green as of the latest run.
