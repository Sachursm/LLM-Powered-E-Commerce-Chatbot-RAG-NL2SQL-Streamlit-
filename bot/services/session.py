"""Redis-backed Telegram chat sessions."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

from bot.config import settings
from bot.services.safety import redact_sensitive_text


SESSION_TTL_SECONDS = 30 * 60
MAX_RECENT_MESSAGES = 8
logger = logging.getLogger(__name__)
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
    """Save a session and refresh its 30-minute inactivity expiry."""
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


async def remember_last_viewed(chat_id: int, product: dict[str, Any]) -> None:
    """Keep the product whose details were shown last, for "add this to my cart"."""
    await update_session(
        chat_id,
        last_viewed_product={
            "id": int(product["id"]),
            "name": redact_sensitive_text(str(product.get("name") or ""), max_length=120),
        },
    )


def append_recent_message(
    messages: list[dict[str, str]], role: str, content: str
) -> list[dict[str, str]]:
    """Return a bounded, redacted message window suitable for Redis/model context."""
    if role not in {"user", "assistant"}:
        raise ValueError("role must be user or assistant")
    updated = list(messages)
    updated.append({"role": role, "content": redact_sensitive_text(content)})
    return updated[-MAX_RECENT_MESSAGES:]


def summarize_pending_workflow(
    pending: dict[str, Any] | None,
    active_context: dict[str, Any] | None = None,
) -> str | None:
    """Build a compact summary of pending work and retained search context."""
    state = pending if pending and pending.get("intent") == "PRODUCT_SEARCH" else active_context
    if not state or state.get("intent") != "PRODUCT_SEARCH":
        return None
    context = state.get("context") or state
    details = ["Pending product search" if pending else "Active product search"]
    for key in ("category", "query", "min_price", "max_price"):
        value = context.get(key)
        if value is not None:
            details.append(f"{key}={redact_sensitive_text(str(value), max_length=100)}")
    waiting_for = pending.get("waiting_for") if pending else None
    if waiting_for:
        details.append(f"waiting_for={waiting_for}")
    return "; ".join(details)[:400]


def summarize_conversation(
    messages: list[dict[str, str]],
    pending: dict[str, Any] | None = None,
    active_context: dict[str, Any] | None = None,
) -> str | None:
    """Create a small, deterministic summary without replacing structured state."""
    user = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), None)
    assistant = next((m.get("content") for m in reversed(messages) if m.get("role") == "assistant"), None)
    if not user and not assistant:
        return None
    state = pending or active_context or {}
    if state.get("intent") == "PRODUCT_SEARCH":
        context = state.get("context") or state
        query = context.get("query")
        if query:
            topic = redact_sensitive_text(str(query), max_length=180)
            response = redact_sensitive_text(str(assistant or ""), max_length=220)
            summary = f"User is looking for {topic}."
            if response:
                summary += f" Assistant replied: {response}"
            return summary[:500]
    user_text = redact_sensitive_text(str(user or ""), max_length=180)
    assistant_text = redact_sensitive_text(str(assistant or ""), max_length=220)
    parts = []
    if user_text:
        parts.append(f"User asked about: {user_text}")
    if assistant_text:
        parts.append(f"Assistant replied: {assistant_text}")
    return " ".join(parts)[:500]


async def save_conversation_memory(
    chat_id: int,
    *,
    recent_messages: list[dict[str, str]],
    pending_workflow: dict[str, Any] | None,
    active_context: dict[str, Any] | None = None,
) -> None:
    """Persist recent turns, pending work, and retained search context in Redis."""
    session = await get_session(chat_id) or {}
    bounded_messages = recent_messages[-MAX_RECENT_MESSAGES:]
    previous_user = next((m["content"] for m in reversed(bounded_messages) if m.get("role") == "user"), None)
    previous_assistant = next((m["content"] for m in reversed(bounded_messages) if m.get("role") == "assistant"), None)
    session["conversation"] = {
        "recent_messages": bounded_messages,
        "summary": summarize_conversation(bounded_messages, pending_workflow, active_context),
        "previous_user_message": previous_user,
        "previous_bot_message": previous_assistant,
    }
    session["pending_workflow"] = pending_workflow
    session["active_context"] = active_context
    await set_session(chat_id, session)
    logger.info("SUMMARY_UPDATED=%s", str(bool(session["conversation"]["summary"])).lower())
