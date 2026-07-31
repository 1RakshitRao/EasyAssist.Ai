"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.board_monitor import run_board_monitor_once
from app.analytics.stats import reset_stats
from app.api.routes_admin_insights import router as admin_insights_router
from app.api.routes_auth import router as auth_router
from app.api.routes_health import router as health_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_kb import router as kb_router
from app.api.routes_notifications import router as notifications_router
from app.api.routes_query import router as query_router
from app.api.routes_stats import router as stats_router
from app.api.routes_tickets import router as tickets_router
from app.audit.db import init_audit_db
from app.auth.users import bootstrap_admin_if_empty
from app.cache.redis_cache import get_cache
from app.config import get_settings
from app.rag.chroma_store import get_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


async def _board_monitor_loop(stop: asyncio.Event) -> None:
    """BoardMonitorAgent — SLA reminders for unresolved escalation board stories."""
    settings = get_settings()
    poll = max(5.0, float(settings.escalation_reminder_poll_seconds or 60.0))
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_board_monitor_once)
        except Exception as exc:
            logger.warning("BoardMonitorAgent loop error: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting Ampcus Helpdesk — seeding KBs and connecting cache")
    reset_stats()
    get_cache()
    store = get_store()
    store.seed_if_empty()
    logger.info("Collection counts: %s", store.collection_counts())
    bootstrap_admin_if_empty()
    init_audit_db()
    stop = asyncio.Event()
    reminder_task = asyncio.create_task(_board_monitor_loop(stop))
    logger.info("BoardMonitorAgent started (escalation board SLA)")
    yield
    stop.set()
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down Ampcus Helpdesk")


app = FastAPI(
    title="Ampcus Helpdesk RAG",
    description="Internal HR/IT/Compliance/Legal RAG chatbot",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(ingest_router)
app.include_router(kb_router)
app.include_router(tickets_router)
app.include_router(notifications_router)
app.include_router(stats_router)
app.include_router(admin_insights_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def ui_home():
    return FileResponse(STATIC_DIR / "index.html")
