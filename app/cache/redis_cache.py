"""Redis FAQ cache with in-memory fallback. Keys use normalized queries only."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class MemoryCache:
    def __init__(self) -> None:
        self._store: Dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> Optional[str]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl: int) -> None:
        self._store[key] = (time.time() + ttl, value)


class ResponseCache:
    def __init__(self) -> None:
        self._memory = MemoryCache()
        self._redis = None
        self.backend = "memory"
        settings = get_settings()
        if settings.redis_url:
            try:
                import redis

                client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
                client.ping()
                self._redis = client
                self.backend = "redis"
                logger.info("Cache backend: redis")
            except Exception:
                logger.warning("Redis unavailable — using in-memory cache", exc_info=True)
                self._redis = None
                self.backend = "memory"
        else:
            logger.info("Cache backend: memory (REDIS_URL not set)")

    @staticmethod
    def make_key(normalized_query: str, department_hint: Optional[str] = None) -> str:
        base = normalized_query.strip().lower()
        hint = (department_hint or "").strip().lower()
        material = f"{hint}|{base}" if hint else base
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"helpdesk:faq:{digest}"

    def get(self, normalized_query: str, department_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        key = self.make_key(normalized_query, department_hint)
        raw: Optional[str] = None
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
            except Exception:
                logger.warning("Redis get failed — falling back to memory", exc_info=True)
                self._redis = None
                self.backend = "memory"
        if raw is None:
            raw = self._memory.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set(
        self,
        normalized_query: str,
        payload: Dict[str, Any],
        department_hint: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        ttl_val = ttl if ttl is not None else settings.cache_ttl_seconds
        key = self.make_key(normalized_query, department_hint)
        raw = json.dumps(payload)
        self._memory.set(key, raw, ttl_val)
        if self._redis is not None:
            try:
                self._redis.setex(key, ttl_val, raw)
            except Exception:
                logger.warning("Redis set failed — memory still holds value", exc_info=True)
                self._redis = None
                self.backend = "memory"


_cache: Optional[ResponseCache] = None


def get_cache() -> ResponseCache:
    global _cache
    if _cache is None:
        _cache = ResponseCache()
    return _cache
