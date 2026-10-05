"""Local semantic intent classifier.

This layer only returns an intent and the semantic-router similarity score. It
does not choose tools, call the LLM/RAG layer, or authorize API operations.
"""

import logging
import math
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any

# semantic-router 0.1.x imports LiteLLM as an optional internal dependency;
# without this flag LiteLLM tries to fetch a model-price map at import time.
# This classifier uses a local Hugging Face encoder and needs no routing API.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

from bot.config import settings  # noqa: E402
from bot.router.routes import (  # noqa: E402
    ROLE_DISAMBIGUATION,
    ROUTE_DESCRIPTIONS,
    ROUTE_UTTERANCES,
    match_command_intent,
)
from bot.services.safety import redact_sensitive_text  # noqa: E402

if TYPE_CHECKING:
    from semantic_router import SemanticRouter

logger = logging.getLogger(__name__)

ENCODER_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SUPPORTED_ROLES = frozenset(
    {"USER", "SELLER", "ADMIN", "HUB_MANAGER", "DELIVERY_AGENT"}
)

COMMON_INTENTS = frozenset(
    {
        "PRODUCT_SEARCH", "PRODUCT_DETAIL", "CATEGORY", "CART", "ORDER",
        "ORDER_STATUS", "ORDER_CANCEL", "PAYMENT", "ADDRESS", "RETURN",
        "REVIEW", "FAQ", "ACCOUNT", "GENERAL_CHAT", "IMAGE",
    }
)
ROLE_INTENTS = {
    "USER": frozenset(),
    "SELLER": frozenset({
        "SELLER_PRODUCT", "SELLER_ORDER", "SELLER_PAYOUT", "PRODUCT_CREATE", "PRODUCT_UPDATE",
    }),
    "ADMIN": frozenset({"ADMIN", "PRODUCT_CREATE", "PRODUCT_UPDATE"}),
    "HUB_MANAGER": frozenset({"DELIVERY_HUB", "DELIVERY_OPERATION"}),
    "DELIVERY_AGENT": frozenset({"DELIVERY_AGENT", "DELIVERY_OPERATION"}),
}


# Routed for every role so other roles get a clear "no permission" reply
# instead of a misroute; only the roles in ROLE_INTENTS may run them.
GATED_INTENTS = frozenset({"PRODUCT_CREATE", "PRODUCT_UPDATE"})


def allowed_intents_for_role(role: str | None) -> tuple[str, ...]:
    """Return semantic candidates for role context; this is not authorization."""
    normalized = role.strip().upper() if isinstance(role, str) else None
    if normalized is not None and normalized not in SUPPORTED_ROLES:
        raise ValueError(f"role must be one of: {', '.join(sorted(SUPPORTED_ROLES))}")
    return tuple(sorted(
        COMMON_INTENTS | GATED_INTENTS | ROLE_INTENTS.get(normalized or "USER", frozenset())
    ))


def role_may_run(intent: str, role: str | None) -> bool:
    """Whether a gated intent belongs to the role; FastAPI still enforces access."""
    if intent not in GATED_INTENTS:
        return True
    normalized = role.strip().upper() if isinstance(role, str) else "USER"
    return intent in ROLE_INTENTS.get(normalized, frozenset())


def _normalize_example(text: str) -> str:
    """Normalize casing, whitespace, and trailing punctuation for exact samples."""
    return " ".join(text.casefold().split()).rstrip(".,!?;:")


EXACT_UTTERANCE_INTENTS = {
    _normalize_example(utterance): intent
    for intent, utterances in ROUTE_UTTERANCES.items()
    for utterance in utterances
}


@lru_cache(maxsize=1)
def _get_router() -> "SemanticRouter":
    """Build the local embedding model and in-memory route index once."""
    # Importing semantic-router also imports LiteLLM and Transformers' broad
    # model registry. Defer that work until a non-empty query is classified.
    from semantic_router import Route, SemanticRouter
    from semantic_router.encoders import HuggingFaceEncoder

    encoder = HuggingFaceEncoder(
        name=ENCODER_NAME,
        tokenizer_kwargs={"local_files_only": True},
        model_kwargs={"local_files_only": True},
        # Return the closest score even for low-confidence input. We apply our
        # configurable fallback threshold ourselves so UNKNOWN retains a real score.
        score_threshold=0.0,
    )
    routes = [
        Route(
            name=intent,
            utterances=list(utterances),
            description=ROUTE_DESCRIPTIONS[intent],
        )
        for intent, utterances in ROUTE_UTTERANCES.items()
    ]
    router = SemanticRouter(
        encoder=encoder,
        top_k=5,
        aggregation="mean",
    )
    # semantic-router 0.1.16 keeps route declarations and the local vector
    # index separate: add() embeds the utterances and populates the index.
    router.add(routes)
    return router


def classify_intent(text: str, role: str | None = None) -> dict[str, Any]:
    """Classify one independent text query.

    ``confidence`` is the real ``RouteChoice.similarity_score`` reported by
    semantic-router, not a calibrated probability. It is ``None`` only when
    the router cannot produce a score (for example, blank input).

    ``role`` is routing context only. Authorization must be performed by the
    FastAPI backend using the authenticated user's credentials.
    """
    if role is not None:
        if not isinstance(role, str) or role.strip().upper() not in SUPPORTED_ROLES:
            raise ValueError(
                f"role must be one of: {', '.join(sorted(SUPPORTED_ROLES))}"
            )
        role = role.strip().upper()

    logger.info("ROLE: %s", role or "UNSPECIFIED")
    if not isinstance(text, str) or not text.strip():
        result = {"intent": "UNKNOWN", "confidence": None, "query": text}
        logger.info('QUERY: "%s"', redact_sensitive_text(text))
        logger.info("ROUTE: UNKNOWN")
        logger.info("CONFIDENCE: unavailable (empty query)")
        return result

    # Credentials must not enter even the local embedding router input.
    safe_text = redact_sensitive_text(text)
    logger.info('QUERY: "%s"', safe_text)
    allowed_intents = allowed_intents_for_role(role)
    normalized_query = _normalize_example(safe_text)
    role_options = ROLE_DISAMBIGUATION.get(normalized_query, {})
    role_intent = role_options.get(role, role_options.get("default"))
    exact_intent = EXACT_UTTERANCE_INTENTS.get(normalized_query)
    command_intent = match_command_intent(safe_text)
    if role_intent in allowed_intents:
        choice = _get_router()(
            text=safe_text.strip(), route_filter=[role_intent], limit=1
        )
        score = choice.similarity_score if choice is not None else None
        confidence = (
            float(score)
            if score is not None and math.isfinite(float(score))
            else None
        )
        intent = role_intent
    elif exact_intent in allowed_intents:
        # The query exactly matches a configured training utterance (after
        # case/whitespace/trailing punctuation normalization), whose cosine
        # similarity to its own embedding is 1.0.
        intent = exact_intent
        confidence = 1.0
    elif command_intent in allowed_intents:
        # A rule match, not a similarity score; it is reported as certain like
        # an exact training utterance.
        intent = command_intent
        confidence = 1.0
    else:
        # Only routes that are appropriate for this role can compete. The
        # role remains context, while FastAPI continues to enforce permissions.
        choice = _get_router()(
            text=safe_text.strip(), route_filter=list(allowed_intents), limit=1
        )
        score = choice.similarity_score if choice is not None else None
        confidence = (
            float(score)
            if score is not None and math.isfinite(float(score))
            else None
        )
        intent = choice.name if choice is not None else "UNKNOWN"
    threshold = settings.ROUTER_CONFIDENCE_THRESHOLD
    if confidence is None or confidence < threshold:
        intent = "UNKNOWN"

    logger.info("ROUTE: %s", intent)
    if confidence is None:
        logger.info("CONFIDENCE: unavailable")
    else:
        logger.info("CONFIDENCE: %.4f", confidence)

    return {
        "intent": intent,
        "confidence": confidence,
        "query": safe_text,
    }
