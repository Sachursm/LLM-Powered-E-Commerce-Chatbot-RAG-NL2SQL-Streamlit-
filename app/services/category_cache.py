"""Shared Redis cache of the category list used by the Telegram bot's category_tool."""

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

# The bot reads and fills this key; the API clears it whenever categories change.
CATEGORY_CACHE_KEY = "bot:categories"
CATEGORY_CACHE_TTL_SECONDS = 60 * 60

_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


async def clear_category_cache() -> None:
    """Drop the cached category list so the bot fetches fresh categories.

    A Redis failure must never fail the category change itself; the cache
    then expires on its own within CATEGORY_CACHE_TTL_SECONDS.
    """
    try:
        await _redis.delete(CATEGORY_CACHE_KEY)
    except (RedisError, OSError):
        logger.warning("Could not clear the category cache; it will expire on its own")
