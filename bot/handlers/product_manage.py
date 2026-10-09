"""Telegram handlers for product drafts: Confirm/Cancel buttons and photos."""

import asyncio
import logging
from collections import defaultdict
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from bot.agent.product_manage import (
    PRODUCT_MANAGE_INTENTS,
    ProductManageTurn,
    missing_fields_question,
    ready_for_confirmation,
    run_product_manage_turn,
)
from bot.handlers.typing import typing_indicator
from bot.middleware.auth_check import user_is_authenticated
from bot.router.semantic import role_may_run
from bot.services.image_upload import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    ImageUploadError,
    upload_product_image,
)
from bot.services.session import append_recent_message, get_session, save_conversation_memory
from bot.tools.category_manage import CATEGORY_MANAGE_INTENTS, submit_category_change
from bot.tools.product_manage import add_image_url, missing_create_fields, submit_product_change

logger = logging.getLogger(__name__)

CALLBACK_PATTERN = r"^pm:(confirm|cancel):[0-9a-f]+$"
_PHOTO_INTENTS = frozenset({"PRODUCT_CREATE", "PRODUCT_UPDATE"})

# Albums arrive as several updates at once; serialize each chat's draft edits
# so one photo's URL is not overwritten by another's session write.
_chat_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def confirm_keyboard(pending: dict[str, Any] | None) -> InlineKeyboardMarkup | None:
    if not pending or pending.get("waiting_for") != "confirmation" or not pending.get("confirm_id"):
        return None
    confirm_id = pending["confirm_id"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm", callback_data=f"pm:confirm:{confirm_id}"),
        InlineKeyboardButton("Cancel", callback_data=f"pm:cancel:{confirm_id}"),
    ]])


def _open_draft(
    session: dict[str, Any],
    intents: frozenset[str] = PRODUCT_MANAGE_INTENTS,
) -> dict[str, Any] | None:
    pending = session.get("pending_workflow")
    return pending if pending and pending.get("intent") in intents else None


async def _save_and_reply(
    message: Message,
    chat_id: int,
    session: dict[str, Any],
    user_text: str,
    answer: str,
    pending: dict[str, Any] | None,
) -> None:
    recent = (session.get("conversation") or {}).get("recent_messages") or []
    recent = append_recent_message(recent, "user", user_text)
    await save_conversation_memory(
        chat_id,
        recent_messages=append_recent_message(recent, "assistant", answer),
        pending_workflow=pending,
        active_context=None,
    )
    await message.reply_text(answer, reply_markup=confirm_keyboard(pending))


async def handle_product_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    chat = update.effective_chat
    message = update.effective_message
    if callback is None or chat is None or message is None:
        return
    await callback.answer()
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.debug("Unable to remove the confirmation keyboard (%s)", type(exc).__name__)
    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return

    _, action, confirm_id = callback.data.split(":", 2)
    async with _chat_locks[chat.id]:
        session = await get_session(chat.id) or {}
        # Confirm/Cancel serve both product and category drafts.
        pending = _open_draft(session, PRODUCT_MANAGE_INTENTS | CATEGORY_MANAGE_INTENTS)
        if (
            not pending
            or pending.get("waiting_for") != "confirmation"
            or pending.get("confirm_id") != confirm_id
        ):
            await message.reply_text("That confirmation has expired. Please check the latest summary.")
            return
        if action == "cancel":
            logger.info("PRODUCT_DRAFT_CANCELLED=true (button)")
            await _save_and_reply(message, chat.id, session, "Cancel", "Cancelled. Nothing was changed.", None)
            return
        role = session.get("role")
        if not role_may_run(pending["intent"], role):
            await _save_and_reply(
                message, chat.id, session, "Confirm", "You don't have permission to make that change.", None
            )
            return
        submit = (
            submit_category_change if pending["intent"] in CATEGORY_MANAGE_INTENTS else submit_product_change
        )
        async with typing_indicator(context.bot, chat.id):
            answer, reopened = await submit(session["token"], role, pending)
        await _save_and_reply(message, chat.id, session, "Confirm", answer, reopened)


def _photo_source(message: Message) -> tuple[str, int | None, str] | None:
    """Return (file_id, size, content type) for a photo or an image document."""
    if message.photo:
        largest = message.photo[-1]
        return largest.file_id, largest.file_size, "image/jpeg"
    document = message.document
    if document and (document.mime_type or "") in ALLOWED_IMAGE_TYPES:
        return document.file_id, document.file_size, document.mime_type
    return None


def _after_photo(intent: str, pending: dict[str, Any], count: int) -> tuple[str, dict[str, Any]]:
    added = f"📷 Photo added ({count} total)."
    if intent == "PRODUCT_CREATE":
        missing = missing_create_fields(pending.get("draft") or {})
        if not missing:
            summary, confirmed = ready_for_confirmation(intent, pending)
            return f"{added}\n\n{summary}", confirmed
        return f"{added} {missing_fields_question(missing)}", {**pending, "waiting_for": "fields", "confirm_id": None}
    if not pending.get("product_id"):
        return f"{added} Which product should it go on? Send its ID or name.", {
            **pending, "waiting_for": "product", "confirm_id": None,
        }
    summary, confirmed = ready_for_confirmation(intent, pending)
    return f"{added}\n\n{summary}", confirmed


async def handle_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return
    source = _photo_source(message)
    if source is None:
        await message.reply_text("Please send the image as a JPEG, PNG, or WebP photo.")
        return

    async with _chat_locks[chat.id]:
        session = await get_session(chat.id) or {}
        # A photo belongs to a create/update draft, never to a delete.
        pending = _open_draft(session, _PHOTO_INTENTS)
        role = session.get("role")
        if pending is None or not role_may_run(pending["intent"], role):
            if role_may_run("PRODUCT_CREATE", role):
                await message.reply_text(
                    "To use this photo for a product, first say \"add a product\" or "
                    "\"update product <ID>\", then send the photo."
                )
            else:
                await message.reply_text("Image handling isn't connected yet.")
            return

        file_id, size, content_type = source
        if size and size > MAX_IMAGE_BYTES:
            await message.reply_text("That photo is larger than 10 MB. Please send a smaller one.")
            return
        async with typing_indicator(context.bot, chat.id):
            try:
                # The Telegram file URL contains the bot token; it is never logged or stored.
                telegram_file = await context.bot.get_file(file_id)
                data = bytes(await telegram_file.download_as_bytearray())
                url = await upload_product_image(data, content_type=content_type)
            except ImageUploadError as exc:
                await message.reply_text(str(exc))
                return
            except Exception as exc:
                logger.warning("Product photo download failed (%s)", type(exc).__name__)
                await message.reply_text("I couldn't read that photo. Please send it again.")
                return

            intent = pending["intent"]
            draft = dict(pending.get("draft") or {})
            count = add_image_url(draft, url)
            pending = {**pending, "draft": draft}
            caption = (message.caption or "").strip()
            if caption:
                # A caption is read like a text reply in the same draft.
                recent = (session.get("conversation") or {}).get("recent_messages") or []
                turn: ProductManageTurn = await run_product_manage_turn(
                    caption, session["token"], role, intent,
                    recent_messages=append_recent_message(recent, "user", caption),
                    pending_workflow=pending,
                )
                answer, pending = f"📷 Photo added ({count} total).\n\n{turn.answer}", turn.pending_workflow
            else:
                answer, pending = _after_photo(intent, pending, count)
        await _save_and_reply(message, chat.id, session, caption or "[photo]", answer, pending)
