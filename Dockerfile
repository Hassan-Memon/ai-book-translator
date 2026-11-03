# Multi-stage: build the React app, then a slim Python image that serves API + static UI.
# The same image runs the worker with a different command (see docker-compose.yml).

FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/alembic.ini ./backend/
COPY backend/app ./backend/app
COPY backend/alembic ./backend/alembic
COPY prompts ./prompts
COPY --from=frontend /ui/dist ./frontend/dist
RUN cd backend && uv sync --frozen --no-dev --no-editable \
    && adduser --disabled-password --gecos "" app \
    && mkdir -p backend/data/uploads backend/data/exports \
    && chown -R app:app /app
USER app
WORKDIR /app/backend
ENV PATH="/app/backend/.venv/bin:$PATH" API_HOST=0.0.0.0 API_PORT=8010 WORKER_INLINE=false
EXPOSE 8010
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8010"]
