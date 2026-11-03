# TranslateBook AI — developer commands. Run from the repo root.
# Windows: use Git Bash or `make` from a Unix-like shell; every target is a plain command you can also copy-paste.

BACKEND=backend
FRONTEND=frontend
UV=uv --directory $(BACKEND)

.PHONY: help install db-up db-down migrate api worker dev test lint fmt typecheck build-frontend up down clean-exports

help:
	@echo "install        install backend (uv) and frontend (npm) dependencies"
	@echo "db-up          start Postgres+pgvector in Docker (port 5433)"
	@echo "migrate        run alembic migrations"
	@echo "build-frontend build the React app into frontend/dist (served by the API)"
	@echo "api            run the API + inline worker on http://127.0.0.1:8010"
	@echo "worker         run a standalone worker process"
	@echo "dev            run Vite dev server on :5173 (proxies /api to :8010)"
	@echo "test           run the backend test suite (needs db-up)"
	@echo "lint / fmt     ruff check / ruff format"
	@echo "up / down      docker compose full stack"

install:
	$(UV) sync
	cd $(FRONTEND) && npm install

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	$(UV) run alembic upgrade head

build-frontend:
	cd $(FRONTEND) && npm run build

api:
	$(UV) run uvicorn app.main:app --host 127.0.0.1 --port 8010 --loop app.core.eventloop:new_event_loop

worker:
	$(UV) run python -m app.worker

dev:
	cd $(FRONTEND) && npm run dev

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check app tests
	$(UV) run ruff format --check app tests
	cd $(FRONTEND) && npm run lint

fmt:
	$(UV) run ruff format app tests
	$(UV) run ruff check --fix app tests

up:
	docker compose up --build -d

down:
	docker compose down
