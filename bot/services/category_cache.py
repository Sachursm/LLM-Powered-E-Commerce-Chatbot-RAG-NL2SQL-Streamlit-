"""Redis cache of the marketplace category list for category_tool."""

import json
import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.schemas.category import CategoryResponse
from bot.config import settings

logger = logging.getLogger(__name__)

# Must match app.services.category_cache.CATEGORY_CACHE_KEY: the API clears
# this key whenever a category is created, renamed, or deleted.
CATEGORY_CACHE_KEY = "bot:categories"
CATEGORY_CACHE_TTL_SECONDS = 60 * 60

_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


async def get_cached_categories() -> list[CategoryResponse] | None:
    """Return cached categories, or ``None`` when missing, invalid, or Redis is down."""
    try:
        payload = await _redis.get(CATEGORY_CACHE_KEY)
    except (RedisError, OSError):
        logger.warning("Category cache unavailable; fetching categories from the API")
        return None
    if payload is None:
        return None
    try:
        return [CategoryResponse.model_validate(item) for item in json.loads(payload)]
    except (TypeError, ValueError, ValidationError):
        logger.warning("Ignoring invalid category cache entry")
        return None


async def cache_categories(categories: list[CategoryResponse]) -> None:
    """Store categories for an hour; a Redis failure only skips caching."""
    if not categories:
        return
    payload = json.dumps([category.model_dump(mode="json") for category in categories])
    try:
        await _redis.set(CATEGORY_CACHE_KEY, payload, ex=CATEGORY_CACHE_TTL_SECONDS)
    except (RedisError, OSError):
        logger.warning("Could not store categories in the cache")
