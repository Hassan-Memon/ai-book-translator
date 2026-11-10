"""FastAPI application factory.

Serves the JSON API under /api/v1, a health check at /health, and (when
frontend/dist exists) the built React app at / with SPA fallback. In dev the
job worker runs inline in this process (WORKER_INLINE=true) so one command
brings up the whole product.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import routes, routes_settings
from app.core.config import APP_VERSION, settings
from app.core.database import dispose_engine, engine
from app.core.logging import setup_logging
from app.worker import run_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.ensure_dirs()
    stop = asyncio.Event()
    worker_task: asyncio.Task | None = None
    if settings.worker_inline:
        worker_task = asyncio.create_task(run_worker(stop, worker_id="inline-api"))
        logger.info("inline worker started")
    try:
        yield
    finally:
        stop.set()
        if worker_task is not None:
            try:
                await asyncio.wait_for(worker_task, timeout=30)
            except (TimeoutError, asyncio.CancelledError):
                worker_task.cancel()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="TranslateBook AI",
        description=(
            "Translate whole books between any two languages: free OCR for scans, "
            "any LLM (cloud or local), a verify-and-retry agent per chunk, and a "
            "human review workflow."
        ),
        version=APP_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes.router)
    app.include_router(routes_settings.router)

    @app.get("/health")
    async def health():
        db = "ok"
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - only when DB is down
            logger.error("health: database check failed: %s", exc)
            db = "error"
        payload = {"status": "ok" if db == "ok" else "degraded", "version": APP_VERSION, "db": db}
        return JSONResponse(payload, status_code=200 if db == "ok" else 503)

    dist = settings.frontend_dist_dir
    index_file = dist / "index.html"
    if index_file.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str, request: Request):
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
                return FileResponse(str(candidate))
            return FileResponse(str(index_file))

        logger.info("serving frontend from %s", dist)
    else:
        logger.warning("frontend/dist not found; API only (run `npm run build` in frontend/)")

    return app


app = create_app()
