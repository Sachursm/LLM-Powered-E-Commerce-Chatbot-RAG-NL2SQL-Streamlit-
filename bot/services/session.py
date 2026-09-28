"""Redis-backed Telegram chat sessions."""

import json
from typing import Any

from redis.asyncio import Redis

from bot.config import settings


SESSION_TTL_SECONDS = 24 * 60 * 60
_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _session_key(chat_id: int) -> str:
    return f"bot:session:{chat_id}"


async def get_session(chat_id: int) -> dict[str, Any] | None:
    """Return the chat session, or ``None`` if no session exists."""
    payload = await _redis.get(_session_key(chat_id))
    if payload is None:
        return None
    return json.loads(payload)


async def set_session(chat_id: int, data: dict[str, Any]) -> None:
    """Save a session and refresh its 24-hour inactivity expiry."""
    await _redis.set(
        _session_key(chat_id),
        json.dumps(data),
        ex=SESSION_TTL_SECONDS,
    )


async def update_session(chat_id: int, **kwargs: Any) -> None:
    """Merge fields into the session and refresh its expiry."""
    session = await get_session(chat_id) or {}
    session.update(kwargs)
    await set_session(chat_id, session)


async def delete_session(chat_id: int) -> None:
    await _redis.delete(_session_key(chat_id))


async def is_logged_in(chat_id: int) -> bool:
    session = await get_session(chat_id)
    return bool(session and session.get("token") and session.get("state") == "LOGGED_IN")


async def get_token(chat_id: int) -> str | None:
    session = await get_session(chat_id)
    return session.get("token") if session else None


async def get_role(chat_id: int) -> str | None:
    session = await get_session(chat_id)
    return session.get("role") if session else None
