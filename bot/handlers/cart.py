"""Telegram side of the cart: the Confirm/Cancel buttons for removing an item or emptying the cart."""

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.typing import typing_indicator
from bot.middleware.auth_check import user_is_authenticated
from bot.services.session import append_recent_message, get_session, save_conversation_memory
from bot.tools.cart import CART_INTENT, submit_cart_change

logger = logging.getLogger(__name__)

CALLBACK_PATTERN = r"^cart:(confirm|cancel):[0-9a-f]+$"


def cart_confirm_keyboard(pending: dict[str, Any] | None) -> InlineKeyboardMarkup | None:
    if (
        not pending
        or pending.get("intent") != CART_INTENT
        or pending.get("waiting_for") != "confirmation"
        or not pending.get("confirm_id")
    ):
        return None
    confirm_id = pending["confirm_id"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm", callback_data=f"cart:confirm:{confirm_id}"),
        InlineKeyboardButton("Cancel", callback_data=f"cart:cancel:{confirm_id}"),
    ]])


async def handle_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    chat = update.effective_chat
    message = update.effective_message
    if callback is None or chat is None or message is None:
        return
    await callback.answer()
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.debug("Unable to remove the cart confirmation keyboard (%s)", type(exc).__name__)
    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return

    _, action, confirm_id = callback.data.split(":", 2)
    session = await get_session(chat.id) or {}
    pending = session.get("pending_workflow") or {}
    if (
        pending.get("intent") != CART_INTENT
        or pending.get("waiting_for") != "confirmation"
        or pending.get("confirm_id") != confirm_id
    ):
        await message.reply_text("That confirmation has expired. Please ask again.")
        return
    if action == "cancel":
        logger.info("CART_CHANGE_CANCELLED=true (button)")
        answer = "Okay, I left your cart as it is."
    else:
        async with typing_indicator(context.bot, chat.id):
            try:
                answer = await submit_cart_change(session["token"], pending)
            except Exception as exc:
                logger.error("Cart change failed (%s)", type(exc).__name__)
                answer = "The cart is temporarily unavailable. Please try again later."
    recent = (session.get("conversation") or {}).get("recent_messages") or []
    recent = append_recent_message(recent, "user", "Confirm" if action == "confirm" else "Cancel")
    # The search list stays, so the user can keep adding from it.
    await save_conversation_memory(
        chat.id,
        recent_messages=append_recent_message(recent, "assistant", answer),
        pending_workflow=None,
        active_context=session.get("active_context"),
    )
    await message.reply_text(answer)
