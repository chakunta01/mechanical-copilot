# AI Manufacturing Copilot — Setup

Production-grade GenAI copilot for manufacturing process planning and quality inspection.
Grounded in your plant knowledge (RAG), validated by deterministic rules, and gated by
human approval at every critical step.

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| Docker (optional, for one-command prod) | 24+ | `docker --version` |

## Quickstart (local, offline-capable)

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"        # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # macOS/Linux

# 2. Seed the knowledge base (runs fully offline)
.venv\Scripts\python ..\data\seed\seed_corpus.py

# 3. Run the API (http://localhost:8000/docs)
.venv\Scripts\python run.py

# 4. Frontend (second terminal)
cd ../frontend
npm install
npm run dev                                  # http://localhost:5173
```

The system runs **fully offline** by default (FakeLLM + hashing embeddings) so you can
try everything without API keys. Register the first account — it becomes plant admin.

## Connecting real models

Edit `.env` (copy from `.env.example`):

```ini
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1      # or Azure / vLLM / Ollama endpoint
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_VISION_MODEL=gpt-4o-mini                # must accept images

EMBEDDINGS_PROVIDER=openai_compatible
EMBEDDINGS_API_KEY=sk-...
EMBEDDINGS_MODEL=text-embedding-3-small
```

Any OpenAI-compatible gateway works (OpenAI, Azure OpenAI, vLLM, LM Studio, Ollama's
OpenAI shim). Restart the backend and re-run `python ..\data\seed\seed_corpus.py` to
re-embed the corpus with the real model.

## Production deployment

```bash
cp .env.example .env      # set SECRET_KEY, POSTGRES_PASSWORD, LLM keys
docker compose -f docker-compose.prod.yml up --build -d
# App on http://localhost:8080 (nginx -> frontend + API proxy)
```

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest        # 25 tests, fully offline
```

## Demo script

```bash
cd backend && .venv\Scripts\python run.py   # terminal 1
python scripts\demo.py                      # terminal 2: end-to-end walkthrough
```

## Architecture

```
data/seed corpus ──▶ ingest (chunk→embed→index) ──▶ vector store
                                                        │
Requirements ──▶ Planner ──▶ Rule engine ──▶ Draft plan ─┤
                      ▲ (RAG)                │           │
                      └──── citations ◀──────┘           ▼
                                               Human approval (submit→approve/reject)
                                                        │
Image ──▶ Quality gate ──▶ VLM analysis ──▶ Verdict ────┤──▶ Disposition + audit
                                                        ▼
                                              Feedback (ratings, corrections)
```

- `backend/app/services/` — RAG (`knowledge`, `chunker`, `embeddings`, `vector_store`),
  planner (`planner`, `plan_schema`), rules (`rules`), inspection (`inspection`,
  `inspection_schema`), Q&A (`qa`), LLM gateway (`llm`).
- `backend/app/api/routes/` — auth, documents, plans, inspections, feedback/QA/dashboard/admin.
- `frontend/src/pages/` — Dashboard, Plans, PlanDetail, Inspections, Ask, Documents, Auth.
- `data/rulepacks/` — YAML rule packs the deterministic validator loads (tune without code).
