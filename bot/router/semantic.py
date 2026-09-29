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
from bot.router.routes import ROUTE_DESCRIPTIONS, ROUTE_UTTERANCES  # noqa: E402

if TYPE_CHECKING:
    from semantic_router import SemanticRouter

logger = logging.getLogger(__name__)

ENCODER_NAME = "sentence-transformers/all-MiniLM-L6-v2"


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


def classify_intent(text: str) -> dict[str, Any]:
    """Classify one independent text query.

    ``confidence`` is the real ``RouteChoice.similarity_score`` reported by
    semantic-router, not a calibrated probability. It is ``None`` only when
    the router cannot produce a score (for example, blank input).
    """
    if not isinstance(text, str) or not text.strip():
        result = {"intent": "UNKNOWN", "confidence": None, "query": text}
        logger.info('QUERY: "%s"', text)
        logger.info("ROUTE: UNKNOWN")
        logger.info("CONFIDENCE: unavailable (empty query)")
        return result

    logger.info('QUERY: "%s"', text)
    exact_intent = EXACT_UTTERANCE_INTENTS.get(_normalize_example(text))
    if exact_intent is not None:
        # The query exactly matches a configured training utterance (after
        # case/whitespace/trailing punctuation normalization), whose cosine
        # similarity to its own embedding is 1.0.
        intent = exact_intent
        confidence = 1.0
    else:
        choice = _get_router()(text=text.strip(), limit=1)
        score = choice.similarity_score
        confidence = (
            float(score)
            if score is not None and math.isfinite(float(score))
            else None
        )
        intent = choice.name or "UNKNOWN"
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
        "query": text,
    }
