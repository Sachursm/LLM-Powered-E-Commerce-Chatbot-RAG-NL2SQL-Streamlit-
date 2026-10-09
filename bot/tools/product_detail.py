"""Product detail: find which product the user means and fetch it from GET /products/{id}.

Search results are numbered on their cards, and their IDs and names are kept
in the search's ``active_context["shown_products"]`` (1 → the first entry, ...).
During a search the search LLM reads that list and calls ``product_detail_tool``
with the Product ID; with no search open, ``resolve_product_reference`` applies
fixed rules to "the 2nd one" / "product 812" instead.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.product import ProductResponse
from bot.services.api_client import api_get
from bot.services.safety import redact_sensitive_text
from bot.tools.product_search import _get_categories

logger = logging.getLogger(__name__)

# Enough for several "Show more" pages without growing the Redis session much.
MAX_SHOWN = 50

_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_ORDINAL = re.compile(r"\b(" + "|".join(_ORDINALS) + r"|\d+(?:st|nd|rd|th))\b", re.IGNORECASE)
_LAST = re.compile(r"\blast\b", re.IGNORECASE)
# "id 812", "product id: 812", "#812" always name the real product ID.
_EXPLICIT_ID = re.compile(r"(?:\bid\s*:?\s*|#\s*)(\d+)\b", re.IGNORECASE)
# "number 2", "no. 2" always name a place in the list.
_LIST_NUMBER = re.compile(r"\b(?:number|no\.?)\s*(\d+)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b(\d+)\b")


@dataclass
class ProductReference:
    """What the user's message points at.

    ``kind`` is "id" (``product_id`` is set), "ambiguous" (``position`` and
    ``product_id`` are the two readings), "out_of_range" (``position`` is past
    the list), "need_list" (a position with no list), or "ask" (no product named).
    """

    kind: str
    product_id: int | None = None
    position: int | None = None
    list_id: int | None = None


def shown_entries(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ID and name of each shown card, as kept in the list."""
    return [
        {"id": int(p["id"]), "name": redact_sensitive_text(str(p.get("name") or ""), max_length=120)}
        for p in products
        if p.get("id") is not None
    ]


def shown_ids(active_context: dict[str, Any] | None) -> list[int]:
    return [int(entry["id"]) for entry in (active_context or {}).get("shown_products") or []]


def remember_shown(previous: list[Any] | None, skip: int, shown: list[Any]) -> list[Any]:
    """Return the list after showing ``shown`` at offset ``skip`` (Show more extends it)."""
    earlier = list(previous or [])[:skip] if skip > 0 else []
    if len(earlier) < skip:
        # The earlier pages are not known (an old session); number this page alone.
        earlier = []
    return (earlier + list(shown))[-MAX_SHOWN:]


def first_position(skip: int, previous: list[Any] | None) -> int:
    """Card number for the first product of a page shown at offset ``skip``."""
    return skip + 1 if skip > 0 and len(previous or []) >= skip else 1


def _by_position(position: int, shown: list[int]) -> ProductReference:
    if not shown:
        return ProductReference("need_list", position=position)
    if position < 1 or position > len(shown):
        return ProductReference("out_of_range", position=position)
    return ProductReference("id", product_id=shown[position - 1], position=position)


def resolve_product_reference(text: str, shown_ids: list[int] | None) -> ProductReference:
    """Apply the rules: explicit ID, list position, or a bare number that may be either."""
    shown = [int(i) for i in (shown_ids or [])]
    match = _EXPLICIT_ID.search(text)
    if match:
        return ProductReference("id", product_id=int(match.group(1)))
    match = _LIST_NUMBER.search(text)
    if match:
        return _by_position(int(match.group(1)), shown)
    match = _ORDINAL.search(text)
    if match:
        word = match.group(1).casefold()
        return _by_position(_ORDINALS.get(word) or int(re.sub(r"\D", "", word)), shown)
    if _LAST.search(text):
        return _by_position(len(shown), shown) if shown else ProductReference("need_list")
    match = _NUMBER.search(text)
    if match:
        number = int(match.group(1))
        if number in shown:
            return ProductReference("id", product_id=number)
        if 1 <= number <= len(shown):
            # "product 2" with two cards on screen: place 2 or the product with ID 2.
            return ProductReference("ambiguous", product_id=number, position=number, list_id=shown[number - 1])
        return ProductReference("id", product_id=number)
    return ProductReference("ask")


async def fetch_product(access_token: str, product_id: int) -> tuple[dict[str, Any] | None, str | None]:
    """Return (product, category name) from GET /products/{id}; product is None when not found."""
    result = await api_get(f"/products/{int(product_id)}", token=access_token)
    status = result.get("status")
    if status == 404:
        return None, None
    if status != 200:
        raise RuntimeError(f"Product lookup failed (status={status})")
    product = ProductResponse.model_validate(result.get("data")).model_dump()
    try:
        categories = await _get_categories(access_token)
        category = next((c.name for c in categories if c.id == product["category_id"]), None)
    except (RuntimeError, ValueError):
        # The category name is a nicety; the product still shows without it.
        category = None
    logger.info("PRODUCT_DETAIL_FETCHED product_id=%s", product_id)
    return product, category


class ProductDetailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(description="The product's Product ID, taken from the shown list or the user's message")


def build_product_detail_tool(access_token: str, found: dict[str, Any]) -> Any:
    """Tool for the search LLM; the fetched product is left in ``found`` for the card."""

    @tool("product_detail_tool", args_schema=ProductDetailInput)
    async def product_detail_tool(product_id: int) -> str:
        """Show the full details of one product the user picked from the shown list or by its Product ID."""
        logger.info("Tool called: product_detail_tool product_id=%s", product_id)
        try:
            product, category = await fetch_product(access_token, product_id)
        except (RuntimeError, ValueError) as exc:
            logger.warning("Product detail lookup failed (%s)", type(exc).__name__)
            return json.dumps({"error": "Product details are temporarily unavailable."})
        if product is None:
            return json.dumps({"found": False, "product_id": product_id})
        found.update(product=product, category=category)
        # The card shows everything; the model only needs enough to write one sentence.
        return json.dumps({"found": True, "product_id": product_id, "name": product["name"], "category": category})

    return product_detail_tool
