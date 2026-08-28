"""Public news headlines endpoint for chat loading state."""

from __future__ import annotations

from fastapi import APIRouter

from app.news.headlines import fetch_headlines

router = APIRouter(tags=["news"])


@router.get("/news/headlines")
async def get_headlines(country: str = "us"):
    """Public endpoint — no auth. Cached server-side for newsapi_cache_seconds."""
    headlines = await fetch_headlines(country)
    return {"headlines": headlines, "count": len(headlines)}
