# Mechanical Copilot — Setup

Mechanical engineering copilot for design, automotive, autonomy, manufacturing, and thermal systems.
Answers combine broad engineering guidance with private, account-scoped plant knowledge, validated workflows,
and human approval where the app supports controlled process planning.

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

The local development stack runs **fully offline** by default (FakeLLM + hashing embeddings) so you can
try everything without API keys. In development, the first account is admin. Public production uses an explicit
administrator setup token; new accounts do not become admin by signing up first.

## Connecting real models

Edit `.env` (copy from `.env.example`):

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=your-server-side-api-key
LLM_MODEL=gpt-6-luna

EMBEDDINGS_PROVIDER=openai_compatible
EMBEDDINGS_MODEL=text-embedding-3-small
```

For OpenAI's first-party models, use `LLM_PROVIDER=openai` and set `OPENAI_API_KEY` on the
backend host. This uses the OpenAI Responses API; the same key is used for embeddings unless
`EMBEDDINGS_API_KEY` is set separately. OpenAI-compatible gateways such as Azure
OpenAI, vLLM, LM Studio, and Ollama can still use `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`,
`LLM_API_KEY`, and a model supported by that gateway. Restart the backend and re-run
`python ..\data\seed\seed_corpus.py` to re-embed the corpus with the real model.

## Public production deployment

This self-hosted production setup runs on a Linux server with Docker Compose. Point a domain's DNS `A` record to
the server's public IP, allow inbound ports 80 and 443, and configure a paid OpenAI-compatible chat and embeddings
provider. Caddy obtains and renews HTTPS certificates automatically. The provider account owner pays model usage.

Create the production environment file and generate separate random secrets:

```bash
cp .env.production.example .env
openssl rand -hex 32      # use for SECRET_KEY
openssl rand -hex 32      # use for ADMIN_BOOTSTRAP_TOKEN
openssl rand -hex 32      # use for POSTGRES_PASSWORD
```

Edit `.env`: set `PUBLIC_DOMAIN`, use the same host in `CORS_ORIGINS`, paste the three generated secrets, and
set the chat and embedding credentials. `IMAGE_API_KEY` is optional; without it, chat works but image generation
is unavailable. This app does not currently have a video generation provider configured.
Deploy from the project root:

```bash
docker compose --env-file .env -f docker-compose.prod.yml up --build -d
docker compose --env-file .env -f docker-compose.prod.yml logs -f
```

Open `https://PUBLIC_DOMAIN`, create the site administrator using the `ADMIN_BOOTSTRAP_TOKEN`, then rotate that
token in `.env` and redeploy. Public users can register without the token and receive private accounts. Plans,
inspections, conversations, and uploaded knowledge are scoped to the account that created them; the bundled seed
documents are shared. PostgreSQL, uploaded files, and Caddy certificates persist in Docker volumes. Back up the
`pgdata` and `uploads` volumes regularly.

The web app is not online until these server, DNS, and provider settings are supplied and the deployment command
is run on that host.

### Launch checklist

- Set a real domain, HTTPS, and restricted `CORS_ORIGINS` before inviting public users.
- Use production secrets and paid model credentials; never commit `.env` or paste provider keys into the app.
- Confirm signup, sign-in, chat, document upload, and account isolation on the deployed host.
- Verify backups and a restore procedure for PostgreSQL and uploaded files.
- Publish the privacy policy, terms, support contact, and model/data-use disclosures required for your audience.
- Monitor API errors, rate limits, model spend, storage, and uptime after release.

The temporary `lhr.life` review tunnel is for demos only. It is not a permanent production host; use the Docker/Caddy
deployment above for a stable public release.

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
