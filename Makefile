.PHONY: install backend frontend seed demo test lint typecheck docker-dev docker-prod clean

install: install-backend install-frontend

install-backend:
	cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" || \
	(.venv/bin/python -m pip install -e ".[dev]")

install-frontend:
	cd frontend && npm install

seed:
	cd backend && .venv/Scripts/python ../data/seed/seed_corpus.py 2>/dev/null || \
	.venv/bin/python ../data/seed/seed_corpus.py

backend:
	cd backend && .venv/Scripts/python run.py 2>/dev/null || .venv/bin/python run.py

frontend:
	cd frontend && npm run dev

demo:
	python scripts/demo.py

test:
	cd backend && .venv/Scripts/python -m pytest 2>/dev/null || .venv/bin/python -m pytest

lint:
	cd backend && .venv/Scripts/python -m ruff check app tests 2>/dev/null || .venv/bin/python -m ruff check app tests

typecheck:
	cd backend && .venv/Scripts/python -m mypy app 2>/dev/null || .venv/bin/python -m mypy app

docker-dev:
	docker compose up --build

docker-prod:
	docker compose -f docker-compose.prod.yml up --build -d

clean:
	rm -rf backend/.venv frontend/node_modules backend/data/*.db backend/data/test_uploads
