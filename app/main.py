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
from app.onboarding.reminder_job import run_onboarding_reminders_once
from app.reservations.reminder_job import run_reservation_reminders_once
from app.reservations.store import seed_guesthouses
from app.infrastructure.store import seed_conference_rooms_if_empty, seed_office_printers_if_empty
from app.analytics.stats import reset_stats
from app.api.routes_admin_insights import router as admin_insights_router
from app.api.routes_auth import router as auth_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_kb import router as kb_router
from app.api.routes_notifications import router as notifications_router
from app.api.routes_onboarding import router as onboarding_router
from app.api.routes_nlp_query import router as nlp_query_router
from app.api.routes_query import router as query_router
from app.api.routes_sessions import router as sessions_router
from app.api.routes_stats import router as stats_router
from app.api.routes_tickets import router as tickets_router
from app.api.routes_reservations import router as reservations_router
from app.api.routes_infrastructure import router as infrastructure_router
from app.api.routes_news import router as news_router
from app.api.routes_fun_facts import router as fun_facts_router
from app.api.routes_feedback import router as feedback_router
from app.audit.db import init_audit_db
from app.auth.users import bootstrap_admin_if_empty
from app.cache.redis_cache import get_cache
from app.config import get_settings
from app.nlp_query.company_facts import seed_company_facts_if_empty
from app.nlp_query.sync import refresh_kb_stats, sync_app_users
from app.rag.chroma_store import get_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


async def _onboarding_reminder_loop(stop: asyncio.Event) -> None:
    """Daily onboarding reminders at configured hour (once per calendar day)."""
    settings = get_settings()
    poll = max(60.0, float(settings.onboarding_reminder_poll_seconds or 300.0))
    target_hour = int(settings.onboarding_reminder_hour or 9)
    last_run_date: str | None = None
    while not stop.is_set():
        try:
            from datetime import date, datetime

            now = datetime.now()
            today = date.today().isoformat()
            if now.hour >= target_hour and last_run_date != today:
                await asyncio.to_thread(run_onboarding_reminders_once, now=now)
                last_run_date = today
        except Exception as exc:
            logger.warning("Onboarding reminder loop error: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll)
        except asyncio.TimeoutError:
            continue


async def _reservation_reminder_loop(stop: asyncio.Event) -> None:
    """Daily guesthouse reminders + 24h auto-approve."""
    settings = get_settings()
    poll = max(60.0, float(settings.reservation_reminder_poll_seconds or 300.0))
    target_hour = int(settings.reservation_reminder_hour or 9)
    last_run_date: str | None = None
    while not stop.is_set():
        try:
            from datetime import date, datetime

            now = datetime.now()
            today = date.today().isoformat()
            if now.hour >= target_hour and last_run_date != today:
                await asyncio.to_thread(run_reservation_reminders_once, now=now)
                last_run_date = today
        except Exception as exc:
            logger.warning("Reservation reminder loop error: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll)
        except asyncio.TimeoutError:
            continue


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
    seed_guesthouses()
    seed_office_printers_if_empty()
    seed_conference_rooms_if_empty()
    seed_company_facts_if_empty()
    try:
        from app.documents.storage import cleanup_old_document_files

        cleanup_old_document_files()
    except Exception:
        logger.warning("document storage cleanup failed on startup", exc_info=True)
    try:
        sync_app_users()
    except Exception:
        logger.warning("app_users sync failed on startup", exc_info=True)
    try:
        refresh_kb_stats(store.collection_counts())
    except Exception:
        logger.warning("kb_stats refresh failed on startup", exc_info=True)
    stop = asyncio.Event()
    reminder_task = asyncio.create_task(_board_monitor_loop(stop))
    onboarding_task = asyncio.create_task(_onboarding_reminder_loop(stop))
    reservation_task = asyncio.create_task(_reservation_reminder_loop(stop))
    logger.info("BoardMonitorAgent started (escalation board SLA)")
    logger.info("Onboarding reminder loop started")
    logger.info("Reservation reminder loop started")
    yield
    stop.set()
    reminder_task.cancel()
    onboarding_task.cancel()
    reservation_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    try:
        await onboarding_task
    except asyncio.CancelledError:
        pass
    try:
        await reservation_task
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
app.include_router(nlp_query_router)
app.include_router(documents_router)
app.include_router(sessions_router)
app.include_router(ingest_router)
app.include_router(kb_router)
app.include_router(tickets_router)
app.include_router(notifications_router)
app.include_router(onboarding_router)
app.include_router(reservations_router)
app.include_router(infrastructure_router)
app.include_router(news_router)
app.include_router(fun_facts_router)
app.include_router(feedback_router)
app.include_router(stats_router)
app.include_router(admin_insights_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def ui_home():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )
