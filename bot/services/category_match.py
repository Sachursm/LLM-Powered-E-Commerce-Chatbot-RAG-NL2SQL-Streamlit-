"""Find the categories closest in meaning to a phrase ("footwear" → shoe categories).

Uses the semantic router's local sentence encoder, so no extra model or API
call is needed. Token overlap alone cannot relate "footwear" to "casual-shoes".
"""

import asyncio
import logging
import math
from functools import lru_cache
from typing import Any

from app.schemas.category import CategoryResponse

logger = logging.getLogger(__name__)

# Below this cosine similarity the "closest" categories are unrelated noise
# (e.g. "car parts" → "trunk"), so none are suggested.
MIN_SIMILARITY = 0.45
# Suggestions stay within this distance of the best match, so a clear winner
# is not padded with weak alternatives.
TOP_MARGIN = 0.12
# A new category this close to an existing one gets a "similar exists" warning.
DUPLICATE_SIMILARITY = 0.70


def normalize_name(name: str) -> str:
    """Compare names ignoring case and hyphen/underscore/space differences."""
    return " ".join(name.replace("-", " ").replace("_", " ").casefold().split())


def find_exact(name: str, categories: list[CategoryResponse]) -> CategoryResponse | None:
    wanted = normalize_name(name)
    return next((c for c in categories if normalize_name(c.name) == wanted), None)


def _encoder() -> Any:
    from bot.router.semantic import _get_router

    return _get_router().encoder


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


@lru_cache(maxsize=4)
def _category_vectors(names: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
    # Embedded once per distinct category list; the API clears the bot's
    # category cache on every change, which yields a new tuple here.
    vectors = _encoder()([normalize_name(name) for name in names])
    return tuple(tuple(_unit(list(v))) for v in vectors)


def _rank(phrase: str, names: tuple[str, ...]) -> list[tuple[float, int]]:
    query = _unit(list(_encoder()([normalize_name(phrase)])[0]))
    scores = [
        (sum(q * c for q, c in zip(query, vector)), index)
        for index, vector in enumerate(_category_vectors(names))
    ]
    return sorted(scores, reverse=True)


async def closest_categories(
    phrase: str,
    categories: list[CategoryResponse],
    *,
    limit: int = 6,
    min_similarity: float = MIN_SIMILARITY,
) -> list[tuple[CategoryResponse, float]]:
    """Return up to ``limit`` categories similar to ``phrase``, best first."""
    if not phrase.strip() or not categories:
        return []
    names = tuple(c.name for c in categories)
    try:
        # Encoding is CPU-bound; keep the Telegram event loop responsive.
        ranked = await asyncio.to_thread(_rank, phrase, names)
    except Exception as exc:
        logger.warning("Category similarity unavailable (%s)", type(exc).__name__)
        return []
    if not ranked or ranked[0][0] < min_similarity:
        return []
    best = ranked[0][0]
    return [
        (categories[index], score)
        for score, index in ranked[:limit]
        if score >= min_similarity and score >= best - TOP_MARGIN
    ]
