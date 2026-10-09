"""Cart tools backed by the FastAPI /cart endpoints.

The API addresses cart items by their cart item ID, but users talk about
products ("product 25", "the blue shirt", "the 2nd one"). The LLM only passes a
Product ID; these tools find the matching cart item. Adding and changing a
quantity write straight away. Removing an item or emptying the cart only
records what to do; ``submit_cart_change`` writes it after the user taps Confirm.
"""

import asyncio
import json
import logging
import secrets
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.cart import CartResponse
from app.schemas.cart_item import CartItemCreate, CartItemResponse, CartItemUpdate
from app.schemas.product import ProductResponse
from bot.services.api_client import api_delete, api_get, api_patch, api_post
from bot.services.safety import redact_sensitive_text

logger = logging.getLogger(__name__)

CART_INTENT = "CART"
UNAVAILABLE = "The cart is temporarily unavailable. Please try again later."
# POST /cart/items allows 15 adds per minute per user.
TOO_FAST = "You're changing the cart too quickly. Please wait a minute and try again."


def _format_price(value: Any) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return ""
    return f"₹{price:,.0f}" if price.is_integer() else f"₹{price:,.2f}"


def _failure(status: int) -> str:
    return TOO_FAST if status == 429 else UNAVAILABLE


async def _get_product(access_token: str, product_id: int) -> dict[str, Any] | None:
    """GET /products/{id}; None when the product does not exist."""
    result = await api_get(f"/products/{int(product_id)}", token=access_token)
    status = result.get("status")
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"Product lookup failed (status={status})")
    return ProductResponse.model_validate(result.get("data")).model_dump()


async def load_cart(access_token: str) -> list[dict[str, Any]]:
    """The user's cart items, oldest first, with each product's name, price and photo.

    GET /cart answers 404 when the user has never had a cart; that is an empty cart.
    """
    result = await api_get("/cart", token=access_token)
    status = result.get("status")
    if status == 404:
        return []
    if status != 200:
        raise RuntimeError(f"Cart lookup failed (status={status})")
    cart = CartResponse.model_validate(result.get("data"))
    items = sorted(cart.items, key=lambda item: item.id)
    products = await asyncio.gather(*(_get_product(access_token, item.product_id) for item in items))
    entries = []
    for item, product in zip(items, products):
        product = product or {}
        entries.append({
            "item_id": item.id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            # A product deleted after it was added still shows, so it can be removed.
            "name": redact_sensitive_text(str(product.get("name") or f"Product {item.product_id}"), max_length=120),
            "price": product.get("price"),
            "stock": product.get("stock"),
            "image_url": (str(product.get("image_url") or "").split(",")[0].strip()) or None,
        })
    logger.info("CART_LOADED items=%s", len(entries))
    return entries


def cart_total(items: list[dict[str, Any]]) -> float:
    return sum(float(item["price"]) * item["quantity"] for item in items if item.get("price") is not None)


def cart_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🛒 Your cart is empty."
    units = sum(item["quantity"] for item in items)
    return (
        f"🛒 Your cart: {len(items)} product{'s' if len(items) != 1 else ''} ({units} item{'s' if units != 1 else ''})"
        f" · Total {_format_price(cart_total(items))}"
    )


def find_item(items: list[dict[str, Any]], product_id: int) -> dict[str, Any] | None:
    return next((item for item in items if item["product_id"] == int(product_id)), None)


def confirmation(action: str, **details: Any) -> dict[str, Any]:
    # A fresh id per question makes buttons on an older question stop working.
    return {
        "intent": CART_INTENT, "waiting_for": "confirmation", "action": action,
        "confirm_id": secrets.token_hex(4), **details,
    }


def confirmation_question(pending: dict[str, Any]) -> str:
    if pending.get("action") == "clear":
        count = pending.get("count") or 0
        return (
            f"Empty your cart? This removes all {count} product{'s' if count != 1 else ''}.\n\n"
            "Tap Confirm to empty it, or Cancel."
        )
    return (
        f"Remove {pending.get('name')} (Product ID {pending.get('product_id')}, quantity "
        f"{pending.get('quantity')}) from your cart?\n\nTap Confirm to remove it, or Cancel."
    )


class AddToCartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(description="Product ID of the product to add")
    quantity: int = Field(default=1, description="How many to add (added to any already in the cart)")


class UpdateCartItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(description="Product ID of a product already in the cart")
    quantity: int = Field(description="The new total quantity for that product; 0 removes it")


class RemoveFromCartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(description="Product ID of the product to remove from the cart")


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def build_cart_tools(access_token: str, items: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> list[Any]:
    """Cart tools for one turn. ``items`` is the cart as loaded at the start of the
    turn; each tool appends what happened to ``outcomes`` for the reply."""

    async def _remove(product_id: int) -> str:
        item = find_item(items, product_id)
        if item is None:
            outcomes.append({"status": "not_in_cart", "product_id": product_id})
            return json.dumps({"in_cart": False, "product_id": product_id})
        outcomes.append({
            "status": "confirm",
            "pending": confirmation(
                "remove", item_id=item["item_id"], product_id=item["product_id"],
                name=item["name"], quantity=item["quantity"],
            ),
        })
        return json.dumps({"waiting_for_confirmation": True, "product_id": product_id})

    @tool("view_cart_tool", args_schema=NoInput)
    async def view_cart_tool() -> str:
        """Show the user's cart."""
        logger.info("Tool called: view_cart_tool")
        outcomes.append({"status": "view"})
        return json.dumps({"shown": True, "products": len(items)})

    @tool("add_to_cart_tool", args_schema=AddToCartInput)
    async def add_to_cart_tool(product_id: int, quantity: int = 1) -> str:
        """Add a product to the cart; the quantity is added to any already there."""
        logger.info("Tool called: add_to_cart_tool product_id=%s quantity=%s", product_id, quantity)
        if quantity <= 0:
            outcomes.append({"status": "invalid_quantity", "product_id": product_id})
            return json.dumps({"error": "quantity must be at least 1"})
        try:
            product = await _get_product(access_token, product_id)
        except (RuntimeError, ValueError):
            outcomes.append({"status": "error", "message": UNAVAILABLE})
            return json.dumps({"error": "unavailable"})
        if product is None:
            outcomes.append({"status": "product_not_found", "product_id": product_id})
            return json.dumps({"found": False, "product_id": product_id})
        payload = CartItemCreate(product_id=product_id, quantity=quantity).model_dump()
        result = await api_post("/cart/items", data=payload, token=access_token)
        status = int(result.get("status") or 503)
        if status == 404:
            outcomes.append({"status": "product_not_found", "product_id": product_id})
            return json.dumps({"found": False, "product_id": product_id})
        if status != 201:
            logger.warning("CART_ADD_FAILED status=%s", status)
            outcomes.append({"status": "error", "message": _failure(status)})
            return json.dumps({"error": "failed"})
        saved = CartItemResponse.model_validate(result.get("data"))
        outcomes.append({
            "status": "added", "product_id": product_id, "added": quantity, "quantity": saved.quantity,
            "name": redact_sensitive_text(product["name"], max_length=120), "stock": product.get("stock"),
        })
        return json.dumps({"added": True, "product_id": product_id, "quantity_in_cart": saved.quantity})

    @tool("update_cart_item_tool", args_schema=UpdateCartItemInput)
    async def update_cart_item_tool(product_id: int, quantity: int) -> str:
        """Set the new total quantity of a product that is already in the cart."""
        logger.info("Tool called: update_cart_item_tool product_id=%s quantity=%s", product_id, quantity)
        if quantity == 0:
            return await _remove(product_id)
        if quantity < 0:
            outcomes.append({"status": "invalid_quantity", "product_id": product_id})
            return json.dumps({"error": "quantity can't be negative"})
        item = find_item(items, product_id)
        if item is None:
            outcomes.append({"status": "not_in_cart", "product_id": product_id})
            return json.dumps({"in_cart": False, "product_id": product_id})
        payload = CartItemUpdate(quantity=quantity).model_dump()
        result = await api_patch(f"/cart/items/{item['item_id']}", data=payload, token=access_token)
        status = int(result.get("status") or 503)
        if status != 200:
            logger.warning("CART_UPDATE_FAILED status=%s", status)
            outcomes.append({"status": "error", "message": _failure(status)})
            return json.dumps({"error": "failed"})
        saved = CartItemResponse.model_validate(result.get("data"))
        outcomes.append({
            "status": "updated", "product_id": product_id, "name": item["name"],
            "quantity": saved.quantity, "stock": item.get("stock"),
        })
        return json.dumps({"updated": True, "product_id": product_id, "quantity_in_cart": saved.quantity})

    @tool("remove_from_cart_tool", args_schema=RemoveFromCartInput)
    async def remove_from_cart_tool(product_id: int) -> str:
        """Remove one product from the cart (the user confirms first)."""
        logger.info("Tool called: remove_from_cart_tool product_id=%s", product_id)
        return await _remove(product_id)

    @tool("clear_cart_tool", args_schema=NoInput)
    async def clear_cart_tool() -> str:
        """Empty the whole cart (the user confirms first)."""
        logger.info("Tool called: clear_cart_tool")
        if not items:
            outcomes.append({"status": "already_empty"})
            return json.dumps({"empty": True})
        outcomes.append({"status": "confirm", "pending": confirmation("clear", count=len(items))})
        return json.dumps({"waiting_for_confirmation": True})

    return [view_cart_tool, add_to_cart_tool, update_cart_item_tool, remove_from_cart_tool, clear_cart_tool]


async def submit_cart_change(access_token: str, pending: dict[str, Any]) -> str:
    """Write a confirmed removal or emptying of the cart; return the reply."""
    action = pending.get("action")
    if action == "remove" and pending.get("item_id"):
        logger.info("CART_REMOVE_SUBMIT product_id=%s", pending.get("product_id"))
        result = await api_delete(f"/cart/items/{int(pending['item_id'])}", token=access_token)
        status = int(result.get("status") or 503)
        if status in {204, 404}:
            # 404: the item was already gone, which is what the user wanted.
            return f"Removed {pending.get('name')} from your cart."
    elif action == "clear":
        logger.info("CART_CLEAR_SUBMIT")
        result = await api_delete("/cart", token=access_token)
        status = int(result.get("status") or 503)
        if status in {204, 404}:
            return "Your cart is now empty."
    else:
        return "That cart change is no longer active. Please try again."
    logger.warning("CART_%s_FAILED status=%s", str(action).upper(), status)
    return _failure(status)
