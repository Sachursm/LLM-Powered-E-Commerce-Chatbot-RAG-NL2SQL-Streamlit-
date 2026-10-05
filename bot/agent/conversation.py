"""Route each Telegram message, including replies to a pending product search."""

import logging
from typing import Any

from bot.agent.intent_fallback import detect_continuation, resolve_fallback_intent
from bot.router.semantic import classify_intent
from bot.services.safety import redact_sensitive_text

logger = logging.getLogger(__name__)

# Workflows that wait for a bare answer such as a price or a category name.
DRAFT_INTENTS = frozenset({"PRODUCT_CREATE", "PRODUCT_UPDATE"})


async def resolve_message_intent(
    text: str,
    role: str | None,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    pending_workflow: dict[str, Any] | None = None,
    active_context: dict[str, Any] | None = None,
    conversation_summary: str | None = None,
    previous_user_message: str | None = None,
    previous_bot_message: str | None = None,
    groq_client: Any | None = None,
) -> dict[str, Any]:
    """Resolve a pending reply or active search before routing an independent request."""
    # A workflow waiting on the user's reply (a search clarification or a
    # product draft) takes precedence over a retained search context.
    if pending_workflow and pending_workflow.get("waiting_for"):
        conversation_context = pending_workflow
    else:
        conversation_context = active_context

    prior_messages = list(recent_messages or [])
    if (
        prior_messages
        and prior_messages[-1].get("role") == "user"
        and prior_messages[-1].get("content") == text
    ):
        prior_messages.pop()
    if previous_user_message is None:
        previous_user_message = next(
            (m.get("content") for m in reversed(prior_messages) if m.get("role") == "user"),
            None,
        )
    if previous_bot_message is None:
        previous_bot_message = next(
            (m.get("content") for m in reversed(prior_messages) if m.get("role") == "assistant"),
            None,
        )
    # Continuation is meaningful only when both sides of the last exchange are
    # available. An active workflow without that exchange still follows normal
    # first-message routing.
    previous_exchange_exists = bool(previous_user_message and previous_bot_message)

    if previous_exchange_exists:
        logger.info("CONTEXT_EXISTS=true")
        continuation = await detect_continuation(
            text,
            previous_user_message,
            previous_bot_message,
            groq_client=groq_client,
        )
        logger.info("ROUTER_SKIPPED=%s", str(continuation == "YES").lower())
        if continuation == "YES":
            return {
                "intent": (
                    conversation_context.get("intent", "PRODUCT_SEARCH")
                    if conversation_context else "PRODUCT_SEARCH"
                ),
                "confidence": None, "fallback_used": False, "continuation": True,
                "continuation_context": conversation_context,
            }
    else:
        logger.info("CONTEXT_EXISTS=false")
        logger.info("ROUTER_SKIPPED=false")

    route = classify_intent(text, role)
    logger.info("ROUTER_CALLED=true")
    logger.info("ROUTER_QUERY=%s", redact_sensitive_text(text, max_length=500))
    logger.info("ROUTER_RESULT: %s", route["intent"])
    if route["intent"] != "UNKNOWN":
        return {**route, "fallback_used": False, "continuation": False}

    if (
        conversation_context is pending_workflow
        and pending_workflow
        and pending_workflow.get("intent") in DRAFT_INTENTS
    ):
        # A bare reply such as "4999" matches no route; with a draft waiting
        # for details it is that draft's answer, so it is not discarded.
        logger.info("UNKNOWN_ROUTED_TO_OPEN_DRAFT=%s", pending_workflow["intent"])
        return {
            **route, "intent": pending_workflow["intent"], "fallback_used": False,
            "continuation": True, "continuation_context": pending_workflow,
        }

    logger.info("Fallback used: true (router result UNKNOWN)")
    intent = await resolve_fallback_intent(
        text,
        role,
        # An independent request must not inherit earlier conversation context.
        recent_messages=None,
        groq_client=groq_client,
    )
    return {
        **route,
        "intent": intent,
        "fallback_used": True,
        "continuation": False,
    }
