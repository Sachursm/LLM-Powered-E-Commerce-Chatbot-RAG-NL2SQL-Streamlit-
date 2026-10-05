"""Telegram bot process entry point: ``python -m bot.main``."""

import logging

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import settings
from bot.handlers.auth import (
    handle_auth_flow,
    login_command,
    register_command,
)
from bot.handlers.commands import (
    help_command,
    logout_command,
    start_command,
)
from bot.agent.conversation import resolve_message_intent
from bot.agent.product_manage import PRODUCT_MANAGE_INTENTS
from bot.handlers.product_cards import send_product_cards
from bot.handlers.product_manage import (
    CALLBACK_PATTERN as PRODUCT_MANAGE_CALLBACK_PATTERN,
    confirm_keyboard,
    handle_product_manage_callback,
    handle_product_photo,
)
from bot.handlers.typing import typing_indicator
from bot.middleware.auth_check import user_is_authenticated
from bot.router.semantic import role_may_run
from bot.services.session import (
    append_recent_message,
    get_session,
    save_conversation_memory,
)

logger = logging.getLogger(__name__)


async def _handle_user_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    bypass_continuation_detector: bool = False,
) -> None:
    message = update.effective_message
    if message is None or not text:
        return

    if not bypass_continuation_detector and await handle_auth_flow(update, context):
        return

    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return

    chat = update.effective_chat
    session = await get_session(chat.id) if chat is not None else None
    if not session or not session.get("token"):
        await message.reply_text("Your session expired. Please /login again.")
        return

    # Show "typing…" for the whole search; Telegram has no other progress signal.
    async with typing_indicator(context.bot, chat.id):
        stored_conversation = session.get("conversation") or {}
        previous_messages = stored_conversation.get("recent_messages") or []
        recent_messages = append_recent_message(previous_messages, "user", text)
        pending = session.get("pending_workflow")
        active_context = session.get("active_context")

        try:
            if bypass_continuation_detector:
                continuation_context = (
                    pending if pending and pending.get("intent") == "PRODUCT_SEARCH"
                    and pending.get("waiting_for") else active_context
                )
                if not continuation_context or continuation_context.get("intent") != "PRODUCT_SEARCH":
                    await message.reply_text("That search is no longer active. Please start a new search.")
                    return
                decision = {
                    "intent": "PRODUCT_SEARCH", "fallback_used": False,
                    "continuation": True, "continuation_context": continuation_context,
                }
                logger.info("CONTINUATION_CHECK=YES (Telegram action)")
                logger.info("ROUTER_SKIPPED=true")
            else:
                decision = await resolve_message_intent(
                    text,
                    session.get("role"),
                    recent_messages=recent_messages,
                    pending_workflow=pending,
                    active_context=active_context,
                    conversation_summary=stored_conversation.get("summary"),
                    previous_user_message=stored_conversation.get("previous_user_message"),
                    previous_bot_message=stored_conversation.get("previous_bot_message"),
                )
        except Exception as exc:
            logger.error("Intent resolution failed (%s)", type(exc).__name__)
            answer = "I couldn't understand that request just now. Please try again."
            if chat is not None:
                await save_conversation_memory(
                    chat.id,
                    recent_messages=append_recent_message(recent_messages, "assistant", answer),
                    pending_workflow=pending,
                    active_context=active_context,
                )
            await message.reply_text(answer)
            return

        if not decision["continuation"]:
            # A NO/new route starts a clean conversational turn. The detector has
            # already seen the prior context; neither router fallbacks nor the
            # main workflow should inherit it.
            recent_messages = recent_messages[-1:]

        logger.info(
            "Resolved request: role=%s intent=%s fallback_used=%s continuation=%s",
            session.get("role", "USER"),
            decision["intent"],
            decision["fallback_used"],
            decision["continuation"],
        )
        updated_pending = None
        updated_active_context = active_context
        reply_markup = None
        search_succeeded = False
        products: list[dict] = []
        if decision["intent"] != "PRODUCT_SEARCH":
            # A newly routed intent replaces an old product-search context.
            updated_active_context = None
            updated_pending = None
        if decision["intent"] == "PRODUCT_SEARCH":
            try:
                from bot.agent.product_search import run_product_search_turn

                continuation_context = decision.get("continuation_context")
                continuing_product_search = (
                    decision["continuation"]
                    and decision["intent"] == "PRODUCT_SEARCH"
                )
                turn_pending = (
                    continuation_context
                    if continuing_product_search and continuation_context is pending
                    else None
                )
                turn_active_context = (
                    continuation_context
                    if continuing_product_search and continuation_context is active_context
                    else None
                )

                turn = await run_product_search_turn(
                    text,
                    session["token"],
                    recent_messages=recent_messages,
                    pending_workflow=turn_pending,
                    active_context=turn_active_context,
                    conversation_summary=(
                        stored_conversation.get("summary") if decision["continuation"] else None
                    ),
                )
                answer = turn.answer
                updated_pending = turn.pending_workflow
                updated_active_context = turn.active_context
                products = turn.products
                search_succeeded = True
            except Exception as exc:
                # Avoid logging request headers, credentials, or provider payloads.
                logger.error("Product search failed (%s)", type(exc).__name__)
                answer = "Product search is temporarily unavailable. Please try again later."
                updated_pending = pending
                updated_active_context = active_context
        elif decision["intent"] in PRODUCT_MANAGE_INTENTS:
            intent = decision["intent"]
            if not role_may_run(intent, session.get("role")):
                answer = "You don't have permission to create or update products."
            else:
                try:
                    from bot.agent.product_manage import run_product_manage_turn

                    continuation_context = decision.get("continuation_context")
                    turn = await run_product_manage_turn(
                        text,
                        session["token"],
                        session.get("role"),
                        intent,
                        recent_messages=recent_messages,
                        # Only a reply to the open draft continues it; a new
                        # "add a product" request starts a fresh draft.
                        pending_workflow=(
                            continuation_context
                            if decision["continuation"] and continuation_context is pending
                            else None
                        ),
                    )
                    answer = turn.answer
                    updated_pending = turn.pending_workflow
                    reply_markup = confirm_keyboard(updated_pending)
                except Exception as exc:
                    logger.error("Product %s failed (%s)", intent.lower(), type(exc).__name__)
                    answer = "Product changes are temporarily unavailable. Please try again later."
                    updated_pending = pending
        elif decision["intent"] == "GENERAL_CHAT":
            answer = "Hi! I can help you search SachuMart products. What are you looking for?"
        elif decision["intent"] == "FAQ":
            answer = "Store policy answers aren't connected yet, but I can help you search products."
        elif decision["intent"] == "UNKNOWN":
            answer = "I can help search products. Tell me what you're looking for."
        else:
            answer = "That request type isn't connected yet. I can help you search products for now."

        if (
            search_succeeded
            and updated_active_context
            and (updated_active_context.get("context") or {}).get("has_more")
        ):
            if not re.search(r"\b(more|another|additional)\b", answer, re.I):
                answer += "\n\nWould you like to see more?"
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("Show more", callback_data="products:more"),
                InlineKeyboardButton("No", callback_data="products:no"),
            ]])

        if chat is not None:
            await save_conversation_memory(
                chat.id,
                recent_messages=append_recent_message(recent_messages, "assistant", answer),
                pending_workflow=updated_pending,
                active_context=updated_active_context,
            )
        if products:
            # Cards first; the assistant's message (and Show more buttons) comes last.
            await send_product_cards(message, products)
        await message.reply_text(answer, reply_markup=reply_markup)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    if message is not None and message.text:
        await _handle_user_text(update, context, message.text)


async def handle_product_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    callback = update.callback_query
    if callback is None:
        return
    await callback.answer()
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.debug("Unable to remove an old product keyboard (%s)", type(exc).__name__)
    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return
    if callback.data == "products:no":
        session = await get_session(chat.id) or {}
        conversation = (session.get("conversation") or {}).get("recent_messages") or []
        recent = append_recent_message(conversation, "user", "No")
        answer = "Okay. Let me know if you'd like to search again."
        await save_conversation_memory(
            chat.id,
            recent_messages=append_recent_message(recent, "assistant", answer),
            pending_workflow=None,
            active_context=None,
        )
        await message.reply_text(answer)
        return
    await _handle_user_text(
        update, context, "Show me more options", bypass_continuation_detector=True
    )


def build_application() -> Application:
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("logout", logout_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        CallbackQueryHandler(handle_product_callback, pattern=r"^products:(more|no)$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_product_manage_callback, pattern=PRODUCT_MANAGE_CALLBACK_PATTERN)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_product_photo)
    )
    return application


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    # HTTPX logs the full Telegram Bot API URL at INFO, including the token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.info("Starting SachuMart Telegram bot")
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
