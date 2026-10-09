"""Cart conversation: view, add, change quantity, remove, and empty the cart.

A plain "show my cart" is answered without an LLM call. Anything else runs one
LLM call that picks the cart tool and the Product ID, using the cart, the
search list from Redis, and the last opened product.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from groq import AsyncGroq

from bot.agent.product_manage import _build_graph
from bot.agent.product_search import _messages_from_history
from bot.config import settings
from bot.prompts.cart import CART_SYSTEM_PROMPT
from bot.services.safety import redact_sensitive_text
from bot.tools.cart import (
    CART_INTENT,
    UNAVAILABLE,
    build_cart_tools,
    cart_summary,
    confirmation_question,
    load_cart,
)

logger = logging.getLogger(__name__)

_CANCEL = re.compile(r"^\s*(cancel|stop|never ?mind|forget it|abort|no)\b\s*[.!]*\s*$", re.IGNORECASE)
# A request that changes the cart or points at a product needs the LLM; one
# with none of these words only asks to see the cart.
_CHANGE_WORDS = re.compile(
    r"\d|\b(?:add|put|place|include|throw|remove|delete|drop|out|off|discard|dump|get\s+rid|clear|empty|wipe"
    r"|reset|purge|flush|clean|start\s+over|cancel|change|update|set|make|increase|decrease|reduce|bump"
    r"|double|adjust|modify|order|this|these|it|one|first|second|third|last|more|less)\b",
    re.IGNORECASE,
)
# Waiting for the user's next cart reply ("remove the 2nd one" after seeing the cart).
_WAITING_FOR_REPLY = {"intent": CART_INTENT, "waiting_for": "reply"}


@dataclass
class CartTurn:
    answer: str
    pending_workflow: dict[str, Any] | None
    # Cart items to show as cards before the answer.
    items: list[dict[str, Any]] = field(default_factory=list)
    show_cart: bool = False


def is_plain_view(text: str) -> bool:
    return not _CHANGE_WORDS.search(text)


def _numbered(entries: list[dict[str, Any]], label: str) -> str:
    return "\n".join(f"{n}. Product ID {e['id']}: {e.get('name') or ''}{label(e)}" for n, e in enumerate(entries, 1))


def _system_prompt(
    items: list[dict[str, Any]],
    shown_products: list[dict[str, Any]] | None,
    last_viewed: dict[str, Any] | None,
) -> str:
    cart = [{"id": i["product_id"], "name": i["name"], "quantity": i["quantity"]} for i in items]
    parts = [CART_SYSTEM_PROMPT]
    parts.append(
        "CART (list number. Product ID: name × quantity, oldest first):\n"
        + _numbered(cart, lambda e: f" × {e['quantity']}")
        if cart else "CART: empty"
    )
    parts.append(
        "SEARCH list (list number. Product ID: name):\n" + _numbered(shown_products, lambda e: "")
        if shown_products else "SEARCH list: none"
    )
    parts.append(
        f"LAST OPENED product: Product ID {last_viewed['id']}: {last_viewed.get('name') or ''}"
        if last_viewed and last_viewed.get("id") else "LAST OPENED product: none"
    )
    return redact_sensitive_text("\n\n".join(parts), max_length=8000)


def _stock_note(outcome: dict[str, Any]) -> str:
    stock = outcome.get("stock")
    if isinstance(stock, int) and outcome["quantity"] > stock:
        return f" Note: only {stock} in stock."
    return ""


def _line(outcome: dict[str, Any]) -> str:
    status = outcome["status"]
    if status == "added":
        return (
            f"✅ Added {outcome['added']} × {outcome['name']} (Product ID {outcome['product_id']}). "
            f"You now have {outcome['quantity']} in your cart." + _stock_note(outcome)
        )
    if status == "updated":
        return f"✅ {outcome['name']} quantity is now {outcome['quantity']}." + _stock_note(outcome)
    if status == "not_in_cart":
        return f"Product ID {outcome['product_id']} isn't in your cart."
    if status == "product_not_found":
        return f"I couldn't find a product with ID {outcome['product_id']}. Check the Product ID on the card."
    if status == "invalid_quantity":
        return "The quantity must be at least 1."
    if status == "already_empty":
        return "Your cart is already empty."
    return outcome.get("message") or UNAVAILABLE


async def _view(access_token: str) -> CartTurn:
    items = await load_cart(access_token)
    return CartTurn(cart_summary(items), dict(_WAITING_FOR_REPLY), items=items, show_cart=True)


async def run_cart_turn(
    text: str,
    access_token: str,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    pending_workflow: dict[str, Any] | None = None,
    shown_products: list[dict[str, Any]] | None = None,
    last_viewed: dict[str, Any] | None = None,
    groq_client: Any | None = None,
) -> CartTurn:
    """Run one cart turn; credentials stay out of model state."""
    waiting_confirmation = bool(pending_workflow and pending_workflow.get("waiting_for") == "confirmation")
    if waiting_confirmation and _CANCEL.match(text):
        logger.info("CART_CHANGE_CANCELLED=true")
        return CartTurn("Okay, I left your cart as it is.", None)
    if waiting_confirmation and is_plain_view(text):
        # "yes" / "ok": only the Confirm button removes.
        return CartTurn("Please use the buttons below.\n\n" + confirmation_question(pending_workflow),
                        pending_workflow)
    if is_plain_view(text):
        logger.info("CART_VIEW_WITHOUT_LLM=true")
        return await _view(access_token)

    items = await load_cart(access_token)
    outcomes: list[dict[str, Any]] = []
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        graph = _build_graph(build_cart_tools(access_token, items, outcomes), client)
        result = await graph.ainvoke(
            {
                "messages": _messages_from_history(recent_messages, text),
                "system_prompt": _system_prompt(items, shown_products, last_viewed),
            },
            config={"recursion_limit": 6},
        )
    finally:
        if own_client:
            await client.close()

    logger.info("CART_OUTCOMES=%s", [outcome["status"] for outcome in outcomes] or ["no_tool"])
    if not outcomes:
        if waiting_confirmation:
            # Only the Confirm button removes; a typed "yes" must not get a
            # model reply that sounds like it was done.
            return CartTurn("Please use the buttons below.\n\n" + confirmation_question(pending_workflow),
                            pending_workflow)
        # No tool call: the model asked which product, or answered a side question.
        answer = redact_sensitive_text(str(result["messages"][-1].content)).strip() or (
            "What would you like to do with your cart?"
        )
        return CartTurn(answer, dict(_WAITING_FOR_REPLY))

    lines = [_line(o) for o in outcomes if o["status"] not in {"view", "confirm"}]
    show_cart = any(o["status"] == "view" for o in outcomes)
    if show_cart:
        if any(o["status"] in {"added", "updated"} for o in outcomes):
            # Show the cart after this turn's changes.
            items = await load_cart(access_token)
        lines.append(cart_summary(items))
    confirm = next((o["pending"] for o in outcomes if o["status"] == "confirm"), None)
    if confirm is not None:
        # One question at a time; another removal can be asked for after this one.
        lines.append(confirmation_question(confirm))
        pending = confirm
    else:
        pending = dict(_WAITING_FOR_REPLY) if show_cart else None
    return CartTurn("\n".join(lines), pending, items=items if show_cart else [], show_cart=show_cart)
