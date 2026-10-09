"""Telegram side of product detail: the reply, the "list or ID?" buttons, and their callback."""

import logging
from dataclasses import dataclass
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.product_cards import send_product_detail
from bot.handlers.typing import typing_indicator
from bot.middleware.auth_check import user_is_authenticated
from bot.services.session import (
    append_recent_message,
    get_session,
    remember_last_viewed,
    save_conversation_memory,
)
from bot.tools.product_detail import fetch_product, resolve_product_reference

logger = logging.getLogger(__name__)

# pd:<product id> shows that product; both "list or ID?" buttons carry a real ID.
CALLBACK_PATTERN = r"^pd:\d+$"
_WAITING = {"intent": "PRODUCT_DETAIL", "waiting_for": "product"}
_ASK = "Which product? Send its number in the list or its Product ID."
_NEXT = "Want details of another one? Send its number in the list or its Product ID."


@dataclass
class ProductDetailTurn:
    answer: str
    pending_workflow: dict[str, Any] | None
    reply_markup: InlineKeyboardMarkup | None = None
    product: dict[str, Any] | None = None
    category: str | None = None


async def _show(access_token: str, product_id: int) -> ProductDetailTurn:
    product, category = await fetch_product(access_token, product_id)
    if product is None:
        return ProductDetailTurn(
            f"I couldn't find a product with ID {product_id}. Check the Product ID on the card.", _WAITING,
        )
    return ProductDetailTurn(_NEXT, None, product=product, category=category)


async def run_product_detail_turn(text: str, access_token: str, shown_ids: list[int] | None) -> ProductDetailTurn:
    """Work out which product the message means; fetch it or ask (no LLM call)."""
    reference = resolve_product_reference(text, shown_ids)
    logger.info(
        "PRODUCT_DETAIL_REFERENCE kind=%s position=%s product_id=%s shown=%s",
        reference.kind, reference.position, reference.product_id, len(shown_ids or []),
    )
    if reference.kind == "id":
        return await _show(access_token, reference.product_id)
    if reference.kind == "ambiguous":
        return ProductDetailTurn(
            f"Do you mean #{reference.position} in the list (Product ID {reference.list_id}) "
            f"or the product with ID {reference.product_id}?",
            None,
            InlineKeyboardMarkup([[
                InlineKeyboardButton(f"#{reference.position} in the list", callback_data=f"pd:{reference.list_id}"),
                InlineKeyboardButton(f"Product ID {reference.product_id}", callback_data=f"pd:{reference.product_id}"),
            ]]),
        )
    if reference.kind == "out_of_range":
        count = len(shown_ids or [])
        return ProductDetailTurn(
            f"There are only {count} products in the list. Send a number from 1 to {count}, or a Product ID.",
            _WAITING,
        )
    if reference.kind == "need_list":
        return ProductDetailTurn(
            "I don't have a product list for you right now. Send the Product ID shown on the card.", _WAITING,
        )
    return ProductDetailTurn(_ASK, _WAITING)


async def handle_product_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A tapped "#2 in the list" / "Product ID 2" button."""
    callback = update.callback_query
    chat = update.effective_chat
    message = update.effective_message
    if callback is None or chat is None or message is None:
        return
    await callback.answer()
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.debug("Unable to remove the product detail keyboard (%s)", type(exc).__name__)
    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return
    session = await get_session(chat.id) or {}
    if not session.get("token"):
        await message.reply_text("Your session expired. Please /login again.")
        return
    product_id = int(callback.data.split(":")[1])
    async with typing_indicator(context.bot, chat.id):
        try:
            turn = await _show(session["token"], product_id)
        except Exception as exc:
            logger.error("Product detail failed (%s)", type(exc).__name__)
            turn = ProductDetailTurn("Product details are temporarily unavailable. Please try again later.", None)
    if turn.product:
        await remember_last_viewed(chat.id, turn.product)
    recent = (session.get("conversation") or {}).get("recent_messages") or []
    recent = append_recent_message(recent, "user", f"[picked product ID {product_id}]")
    # The search list stays, so another "the 3rd one" still works.
    await save_conversation_memory(
        chat.id,
        recent_messages=append_recent_message(recent, "assistant", turn.answer),
        pending_workflow=turn.pending_workflow,
        active_context=session.get("active_context"),
    )
    if turn.product:
        await send_product_detail(message, turn.product, turn.category)
    await message.reply_text(turn.answer)
