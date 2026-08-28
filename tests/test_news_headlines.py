"""Tests for NewsAPI headlines fetch and endpoint."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.news.headlines import (
    _clean_title,
    _parse_articles,
    fetch_headlines,
    reset_headlines_cache,
)


def test_clean_title_strips_source_suffix():
    assert _clean_title("Markets rally on jobs data - CNN") == "Markets rally on jobs data"


def test_clean_title_skips_removed():
    assert _clean_title("[Removed]") is None
    assert _clean_title("") is None


def test_parse_articles_filters_and_shapes():
    articles = [
        {
            "title": "Headline One - BBC News",
            "source": {"name": "BBC News"},
            "publishedAt": "2026-08-13T10:00:00Z",
            "url": "https://example.com/1",
        },
        {"title": "[Removed]", "source": {"name": "X"}, "publishedAt": "", "url": ""},
    ]
    out = _parse_articles(articles, category="politics")
    assert len(out) == 1
    assert out[0]["title"] == "Headline One"
    assert out[0]["source"] == "BBC News"
    assert out[0]["published_at"] == "2026-08-13"
    assert out[0]["url"] == "https://example.com/1"
    assert out[0]["category"] == "politics"


def test_dedupe_headlines():
    from app.news.headlines import _dedupe_headlines

    items = [
        {"title": "Same story", "category": "technology"},
        {"title": "Same story", "category": "politics"},
        {"title": "Other story", "category": "politics"},
    ]
    out = _dedupe_headlines(items)
    assert len(out) == 2
    assert out[0]["title"] == "Same story"
    assert out[1]["title"] == "Other story"


@pytest.mark.asyncio
async def test_fetch_headlines_empty_when_no_api_key(monkeypatch):
    reset_headlines_cache()
    monkeypatch.setenv("NEWSAPI_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()

    result = await fetch_headlines()
    assert result == []


@pytest.mark.asyncio
async def test_fetch_headlines_uses_cache(monkeypatch):
    reset_headlines_cache()
    monkeypatch.setenv("NEWSAPI_KEY", "test-key")
    monkeypatch.setenv("NEWSAPI_CACHE_SECONDS", "900")
    from app.config import get_settings

    get_settings.cache_clear()

    tech_response = MagicMock()
    tech_response.raise_for_status = MagicMock()
    tech_response.json.return_value = {
        "articles": [
            {
                "title": "Cached tech story - Reuters",
                "source": {"name": "Reuters"},
                "publishedAt": "2026-08-13T08:00:00Z",
                "url": "https://example.com/tech",
            }
        ]
    }
    politics_response = MagicMock()
    politics_response.raise_for_status = MagicMock()
    politics_response.json.return_value = {
        "articles": [
            {
                "title": "Cached politics story - AP",
                "source": {"name": "AP"},
                "publishedAt": "2026-08-13T09:00:00Z",
                "url": "https://example.com/politics",
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[tech_response, politics_response])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.news.headlines.httpx.AsyncClient", return_value=mock_client):
        first = await fetch_headlines()
        second = await fetch_headlines()

    assert len(first) == 2
    assert {h["category"] for h in first} == {"technology", "politics"}
    assert second == first
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_fetch_headlines_returns_stale_cache_on_timeout(monkeypatch):
    reset_headlines_cache()
    monkeypatch.setenv("NEWSAPI_KEY", "test-key")
    monkeypatch.setenv("NEWSAPI_CACHE_SECONDS", "0")
    from app.config import get_settings
    import app.news.headlines as headlines_mod

    get_settings.cache_clear()

    headlines_mod._cache["headlines"] = [{"title": "Stale", "source": "", "published_at": "", "url": ""}]
    headlines_mod._cache["fetched_at"] = time.time() - 10

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.news.headlines.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_headlines()

    assert len(result) == 1
    assert result[0]["title"] == "Stale"


def test_get_headlines_endpoint(client, monkeypatch):
    reset_headlines_cache()
    monkeypatch.setenv("NEWSAPI_KEY", "")

    from app.config import get_settings

    get_settings.cache_clear()

    res = client.get("/news/headlines")
    assert res.status_code == 200
    data = res.json()
    assert "headlines" in data
    assert "count" in data
    assert data["count"] == len(data["headlines"])
