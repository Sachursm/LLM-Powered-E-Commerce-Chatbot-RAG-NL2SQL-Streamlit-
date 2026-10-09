"""Render products as Telegram photo cards: search results and one product's details."""

import html
import logging
from typing import Any

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# Telegram rejects photo captions longer than 1024 characters.
_DESCRIPTION_LIMIT = 300
_CAPTION_LIMIT = 1024


def _format_price(price: Any) -> str:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return ""
    return f"₹{value:,.0f}" if value.is_integer() else f"₹{value:,.2f}"


def build_product_caption(
    product: dict[str, Any],
    *,
    position: int | None = None,
    description_limit: int | None = _DESCRIPTION_LIMIT,
    category: str | None = None,
) -> str:
    """HTML caption: name, description, price/rating, stock, and the product ID.

    ``position`` numbers a search card so the user can say "the 2nd one";
    the ID lets them ask for that product directly.
    """
    name = html.escape(str(product.get("name") or "Product"))
    lines = [f"<b>{position}. {name}</b>" if position else f"<b>{name}</b>"]
    description = str(product.get("description") or "").strip()
    if description:
        if description_limit is not None and len(description) > description_limit:
            description = description[:description_limit].rstrip() + "…"
        lines.append(html.escape(description))

    details = [_format_price(product.get("price"))]
    rating = product.get("rating")
    if rating is not None:
        count = product.get("ratings_count")
        details.append(f"⭐ {rating}" + (f" ({count} ratings)" if count else ""))
    lines.append(" · ".join(part for part in details if part))

    stock = product.get("stock")
    if isinstance(stock, int) and stock > 0:
        lines.append(f"✅ In stock ({stock})")
    else:
        lines.append("❌ Out of stock")
    if category:
        lines.append(f"Category: {html.escape(category)}")
    if product.get("id") is not None:
        lines.append(f"🆔 Product ID: {product['id']}")
    return "\n".join(line for line in lines if line)


async def _send_card(message: Message, image_url: str | None, caption: str) -> None:
    """Send a photo card; a card whose image fails falls back to text."""
    if image_url:
        try:
            await message.reply_photo(photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
            return
        except TelegramError as exc:
            logger.warning("Product image could not be sent (%s); using text card", type(exc).__name__)
    await message.reply_text(caption, parse_mode=ParseMode.HTML)


async def send_product_cards(
    message: Message,
    products: list[dict[str, Any]],
    *,
    start: int | None = None,
) -> None:
    """Send one card per product, numbered from ``start`` when given."""
    for offset, product in enumerate(products):
        position = start + offset if start is not None else None
        await _send_card(message, product.get("image_url"), build_product_caption(product, position=position))


def build_cart_caption(item: dict[str, Any], position: int) -> str:
    """HTML caption for one cart line: name, price × quantity, and the product ID."""
    lines = [f"<b>{position}. {html.escape(str(item.get('name') or 'Product'))}</b>"]
    price = item.get("price")
    if price is None:
        lines.append(f"Quantity: {item['quantity']} · no longer available")
    else:
        lines.append(
            f"{_format_price(price)} × {item['quantity']} = {_format_price(float(price) * item['quantity'])}"
        )
        stock = item.get("stock")
        if isinstance(stock, int) and stock < item["quantity"]:
            lines.append(f"⚠️ Only {stock} in stock" if stock > 0 else "❌ Out of stock")
    lines.append(f"🆔 Product ID: {item['product_id']}")
    return "\n".join(lines)


async def send_cart_cards(message: Message, items: list[dict[str, Any]]) -> None:
    """Send one numbered card per cart item, oldest first."""
    for position, item in enumerate(items, start=1):
        await _send_card(message, item.get("image_url"), build_cart_caption(item, position))


async def send_product_detail(message: Message, product: dict[str, Any], category: str | None) -> None:
    """Send one product with its full description and category."""
    image_url = (str(product.get("image_url") or "").split(",")[0].strip()) or None
    caption = build_product_caption(product, description_limit=None, category=category)
    if len(caption) <= _CAPTION_LIMIT:
        await _send_card(message, image_url, caption)
        return
    # A long description does not fit a photo caption: photo card first, full text after.
    await _send_card(message, image_url, build_product_caption(product, category=category))
    # Telegram text messages stop at 4096 characters.
    await message.reply_text(html.escape(str(product.get("description") or "")[:4000]), parse_mode=ParseMode.HTML)
