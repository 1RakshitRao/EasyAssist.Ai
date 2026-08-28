"""Headlines fetcher with in-memory cache. Calls NewsAPI once per cache window."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_cache: dict = {
    "headlines": [],
    "fetched_at": 0.0,
}

NEWSAPI_TOP_URL = "https://newsapi.org/v2/top-headlines"
NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"


def _clean_title(title: str) -> str | None:
    if not title or "[Removed]" in title:
        return None
    if " - " in title:
        title = title.rsplit(" - ", 1)[0].strip()
    return title or None


def _parse_articles(articles: list, *, category: str = "") -> list[dict]:
    headlines = []
    for article in articles:
        title = _clean_title(article.get("title", ""))
        if not title:
            continue
        headlines.append(
            {
                "title": title,
                "source": article.get("source", {}).get("name", ""),
                "published_at": (article.get("publishedAt") or "")[:10],
                "url": article.get("url", ""),
                "category": category,
            }
        )
    return headlines


def _dedupe_headlines(headlines: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for item in headlines:
        title = item.get("title") or ""
        if not title or title in seen:
            continue
        seen.add(title)
        unique.append(item)
    return unique


async def _fetch_articles(client: httpx.AsyncClient, url: str, params: dict) -> list:
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("articles", [])
    except Exception as exc:
        logger.warning("NewsAPI fetch failed url=%s: %s", url, exc)
        return []


async def fetch_headlines(country: str = "us") -> list[dict]:
    """
    Returns up to 10 clean headline dicts.
    Serves from cache if fetched within newsapi_cache_seconds.
    Falls back to empty list or stale cache on any error.
    """
    settings = get_settings()
    now = time.time()
    age = now - _cache["fetched_at"]

    if _cache["headlines"] and age < settings.newsapi_cache_seconds:
        logger.info("Headlines served from cache (age=%ss)", int(age))
        return _cache["headlines"]

    if not settings.newsapi_key:
        logger.warning("NEWSAPI_KEY not set — returning empty headlines")
        return []

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            tech_articles, politics_articles = await asyncio.gather(
                _fetch_articles(
                    client,
                    NEWSAPI_TOP_URL,
                    {
                        "country": country,
                        "category": "technology",
                        "pageSize": 10,
                        "apiKey": settings.newsapi_key,
                    },
                ),
                _fetch_articles(
                    client,
                    NEWSAPI_EVERYTHING_URL,
                    {
                        "q": "politics",
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": 10,
                        "apiKey": settings.newsapi_key,
                    },
                ),
            )

        headlines = _dedupe_headlines(
            _parse_articles(tech_articles, category="technology")
            + _parse_articles(politics_articles, category="politics")
        )
        if headlines:
            _cache["headlines"] = headlines
            _cache["fetched_at"] = now
            logger.info(
                "Fetched %d headlines from NewsAPI (tech=%d politics=%d)",
                len(headlines),
                len(tech_articles),
                len(politics_articles),
            )
            return headlines

        if _cache["headlines"]:
            logger.warning("NewsAPI returned no headlines — serving stale cache")
            return _cache["headlines"]
        return []

    except httpx.TimeoutException:
        logger.warning("NewsAPI request timed out")
        return _cache["headlines"]

    except Exception as exc:
        logger.error("NewsAPI error: %s", exc)
        return _cache["headlines"]


def reset_headlines_cache() -> None:
    """Clear cache — useful in tests."""
    _cache["headlines"] = []
    _cache["fetched_at"] = 0.0
