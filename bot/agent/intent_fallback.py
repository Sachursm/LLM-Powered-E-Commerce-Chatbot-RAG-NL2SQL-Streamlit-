"""LLM intent fallback for low-confidence semantic-router results."""

import logging
import json
import re
from typing import Any

from groq import AsyncGroq

from bot.config import settings
from bot.router.semantic import allowed_intents_for_role
from bot.services.safety import redact_sensitive_text

logger = logging.getLogger(__name__)


def _recent_context(messages: list[dict[str, str]] | None) -> list[dict[str, str]]:
    safe_messages = []
    for item in (messages or [])[-6:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            safe_messages.append({"role": role, "content": redact_sensitive_text(content, max_length=500)})
    return safe_messages


async def resolve_fallback_intent(
    query: str,
    role: str | None,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    groq_client: Any | None = None,
) -> str:
    """Ask Groq to disambiguate UNKNOWN; validate its answer against role candidates."""
    candidates = allowed_intents_for_role(role)
    prompt = (
        "Classify the latest user message into exactly one allowed high-level intent. "
        "PRODUCT_SEARCH means browsing/availability/filtering products. FAQ means a "
        "policy or service question. GENERAL_CHAT means greetings or casual chat. "
        "Use UNKNOWN if no allowed intent fits. Do not choose tools, infer permissions, "
        "or answer the user. Return only the intent label.\n"
        f"Allowed intents: {', '.join(candidates)}, UNKNOWN.\n"
        f"Recent context (may be empty): {_recent_context(recent_messages)!r}\n"
        f"Latest message: {redact_sensitive_text(query)!r}"
    )
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        response = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You classify intent only. Do not authorize users or select tools.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=24,
            # A single intent label needs little reasoning. Product-search calls
            # keep the default effort because they choose the search filters.
            reasoning_effort="low",
        )
        raw = response.choices[0].message.content or ""
        decision = raw.strip().strip("`\"' ").upper()
        if decision.startswith("{"):
            import json

            try:
                decision = str(json.loads(decision).get("intent", "UNKNOWN")).upper()
            except (ValueError, AttributeError):
                decision = "UNKNOWN"
        elif decision not in candidates and decision != "UNKNOWN":
            labels = {label for label in candidates} | {"UNKNOWN"}
            match = re.search(r"\b(" + "|".join(sorted(labels, key=len, reverse=True)) + r")\b", decision)
            decision = match.group(1) if match else "UNKNOWN"
        if decision not in candidates and decision != "UNKNOWN":
            decision = "UNKNOWN"
        logger.info("LLM decision after router fallback: %s", decision)
        return decision
    finally:
        if own_client:
            await client.close()


async def detect_continuation(
    query: str,
    previous_user_message: str | None,
    previous_bot_message: str | None,
    *,
    groq_client: Any | None = None,
) -> str:
    """Return strict YES/NO for whether a user message continues active context.

    This detector does not classify intent, choose tools, answer, or authorize.
    Invalid model output fails closed to NO.
    """
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    prompt = (
        "Determine whether the current user message continues or depends on the previous "
        "exchange. Judge it using the previous user and assistant messages; do not "
        "treat the current message as a standalone query or decide whether it is complete "
        "by itself. A short reply that plausibly answers a question or clarification in "
        "the previous assistant response is a continuation. Refinements, added constraints, "
        "confirmations, and references to the previous response also continue it. A clearly "
        "unrelated request does not. Do not classify intent, generate a query, choose a tool, "
        "or answer the user. Return ONLY YES or NO.\n"
        f"Previous user message: {redact_sensitive_text(previous_user_message or '', max_length=500)}\n"
        f"Previous assistant response: {redact_sensitive_text(previous_bot_message or '', max_length=500)}\n"
        f"Current user message: {redact_sensitive_text(query, max_length=500)}"
    )
    # Temporary diagnostics for identifying whether bad decisions come from
    # stale/missing conversation state, the configured model, or its output.
    # Redaction and length limits keep credentials and oversized text out of logs.
    logger.info(
        "CONTINUATION_PREVIOUS_USER=%s",
        redact_sensitive_text(previous_user_message or "", max_length=500),
    )
    logger.info(
        "CONTINUATION_PREVIOUS_BOT=%s",
        redact_sensitive_text(previous_bot_message or "", max_length=500),
    )
    logger.info("CONTINUATION_CURRENT=%s", redact_sensitive_text(query, max_length=500))
    logger.info("CONTINUATION_MODEL=%s", settings.CONTINUATION_MODEL)
    try:
        response = await client.chat.completions.create(
            model=settings.CONTINUATION_MODEL,
            messages=[
                {"role": "system", "content": "Classify conversation continuation only. Return exactly YES or NO. Do not classify intent, select tools, answer, call APIs, or authorize actions."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            # Reasoning models may consume a small token budget before emitting
            # their final YES/NO text. Leave enough room for the final answer.
            max_tokens=128,
            # YES/NO needs little reasoning; see resolve_fallback_intent.
            reasoning_effort="low",
        )
        raw_output = response.choices[0].message.content or ""
        logger.info(
            "CONTINUATION_RAW_OUTPUT=%s",
            redact_sensitive_text(raw_output, max_length=200),
        )
        normalized = raw_output.strip().upper()
        decision = normalized if normalized in {"YES", "NO"} else "NO"
        if decision == "NO" and normalized not in {"NO", ""}:
            logger.warning("Continuation detector returned invalid output; treating as NO")
        logger.info("CONTINUATION_PARSED_RESULT=%s", decision)
        logger.info("CONTINUATION_CHECK=%s", decision)
        return decision
    except Exception as exc:
        logger.warning("Continuation detector unavailable (%s); treating as NO", type(exc).__name__)
        logger.info("CONTINUATION_CHECK=NO")
        return "NO"
    finally:
        if own_client:
            await client.close()


# Backward-compatible name for callers/tests from the earlier routing flow.
async def resolve_active_context_action(
    query: str,
    role: str | None,
    active_context: dict[str, Any],
    *,
    recent_messages: list[dict[str, str]] | None = None,
    groq_client: Any | None = None,
) -> str:
    history = _recent_context(recent_messages)
    previous_user = next((m["content"] for m in reversed(history) if m["role"] == "user" and m["content"] != query), None)
    previous_assistant = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), None)
    result = await detect_continuation(
        query, previous_user, previous_assistant, groq_client=groq_client,
    )
    return "CONTINUE" if result == "YES" else "NEW_REQUEST"
