"""Render product-search results as Telegram photo cards."""

import html
import logging
from typing import Any

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# Telegram rejects photo captions longer than 1024 characters.
_DESCRIPTION_LIMIT = 300


def _format_price(price: Any) -> str:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return ""
    return f"₹{value:,.0f}" if value.is_integer() else f"₹{value:,.2f}"


def build_product_caption(product: dict[str, Any]) -> str:
    """HTML caption: name, description, price/rating, stock."""
    lines = [f"<b>{html.escape(str(product.get('name') or 'Product'))}</b>"]
    description = str(product.get("description") or "").strip()
    if description:
        if len(description) > _DESCRIPTION_LIMIT:
            description = description[:_DESCRIPTION_LIMIT].rstrip() + "…"
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
    return "\n".join(line for line in lines if line)


async def send_product_cards(message: Message, products: list[dict[str, Any]]) -> None:
    """Send one card per product; a card whose image fails falls back to text."""
    for product in products:
        caption = build_product_caption(product)
        image_url = product.get("image_url")
        if image_url:
            try:
                await message.reply_photo(photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
                continue
            except TelegramError as exc:
                logger.warning("Product image could not be sent (%s); using text card", type(exc).__name__)
        await message.reply_text(caption, parse_mode=ParseMode.HTML)
