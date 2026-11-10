# TranslateBook AI: developer commands. Run from the repo root.
#
#   make setup   first time: .env, database, dependencies, UI build, migrations
#   make start   every day: start the database, migrate, run the app on :8010
#   make all     both of the above in one go
#
# Every recipe works under cmd.exe (what GNU make uses on Windows from
# PowerShell) and under sh (macOS, Linux, Git Bash): only `&&`, `||` and
# plain commands, no bash-only syntax.

BACKEND=backend
FRONTEND=frontend
UV=uv --directory $(BACKEND)
PORT=8010

.DEFAULT_GOAL := help
.PHONY: help all setup start env install db-up db-down migrate build-frontend api worker dev test lint fmt up down eval cf-setup cf-connect

help:
	@echo make setup          first-time setup: .env, database, dependencies, UI build, migrations
	@echo make start          start the database, apply migrations, run the app on http://127.0.0.1:$(PORT)
	@echo make all            setup + start in one go
	@echo ---
	@echo make env            create .env from .env.example if it does not exist
	@echo make install        install backend (uv) and frontend (npm) dependencies
	@echo make db-up          start Postgres in Docker (port 5433) and wait until healthy
	@echo make db-down        stop the Docker services
	@echo make migrate        run alembic migrations
	@echo make build-frontend build the React app into frontend/dist (served by the API)
	@echo make api            run the API + inline worker on http://127.0.0.1:$(PORT)
	@echo make worker         run a standalone worker process
	@echo make dev            run the Vite dev server on :5173 (proxies /api to :$(PORT))
	@echo make test           run the backend test suite (starts the database first)
	@echo make lint / fmt     ruff + oxlint / ruff format
	@echo make up / down      full stack in Docker (API + worker + UI)
	@echo make eval           validate the golden set and run the evaluation with the .env model
	@echo make cf-setup       once: Cloudflare Pages project, secrets, first deploy
	@echo make cf-connect     put the running app online through a Cloudflare tunnel

# --- one-shot targets -------------------------------------------------------

all: setup start

setup: env db-up install build-frontend migrate
	@echo Setup complete. Run: make start

start: db-up migrate api

# --- building blocks ----------------------------------------------------------

env:
	@uv run --no-project python -c "import os, shutil; os.path.exists('.env') or (shutil.copy('.env.example', '.env'), print('created .env from .env.example'))"

install:
	$(UV) sync
	cd $(FRONTEND) && npm install

# `docker start` covers a translatebook-db container created from another folder.
db-up:
	docker compose up -d --wait db || docker start translatebook-db

db-down:
	docker compose down

migrate:
	$(UV) run alembic upgrade head

build-frontend:
	cd $(FRONTEND) && npm run build

# --loop: async psycopg (LangGraph checkpointer) needs a selector event loop on Windows.
api:
	$(UV) run uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --loop app.core.eventloop:new_event_loop

worker:
	$(UV) run python -m app.worker

dev:
	cd $(FRONTEND) && npm run dev

test: db-up
	$(UV) run pytest -q

lint:
	$(UV) run ruff check app tests
	$(UV) run ruff format --check app tests
	cd $(FRONTEND) && npm run lint

fmt:
	$(UV) run ruff format app tests
	$(UV) run ruff check --fix app tests

up:
	docker compose --profile full up --build -d

down:
	docker compose --profile full down

# --- evaluation and Cloudflare --------------------------------------------------

eval:
	$(UV) run translatebook eval validate
	$(UV) run translatebook eval run --split dev

cf-setup:
	uv run --no-project python deploy/cloudflare/connect.py setup

cf-connect:
	uv run --no-project python deploy/cloudflare/connect.py
