"""Telegram buttons for categories: suggestions, paged lists, browsing, and picks."""

import json
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from bot.agent.category_manage import CategoryTurn, apply_category_pick
from bot.handlers.product_cards import send_product_cards
from bot.handlers.product_manage import _chat_locks, confirm_keyboard
from bot.handlers.typing import typing_indicator
from bot.middleware.auth_check import user_is_authenticated
from bot.services.session import append_recent_message, get_session, save_conversation_memory
from bot.tools.category_manage import CATEGORY_MANAGE_INTENTS
from bot.tools.product_detail import first_position, remember_shown, shown_entries
from bot.tools.product_search import PRODUCT_PAGE_SIZE, _get_categories, build_product_search_tools

logger = logging.getLogger(__name__)

# cat:* buttons browse a category's products; cm:* buttons pick a category for
# a rename/delete draft. Both page through the full list with *:page:<skip>.
CALLBACK_PATTERN = r"^(?:cat:(?:browse:\d+:\d+|page:\d+)|cm:(?:pick:\d+|page:\d+))$"
CATEGORY_PAGE_SIZE = 10


def _rows(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def _category_button(category: dict[str, Any], picking: bool) -> InlineKeyboardButton:
    data = f"cm:pick:{category['id']}" if picking else f"cat:browse:{category['id']}:0"
    return InlineKeyboardButton(category["name"], callback_data=data)


async def _page_keyboard(token: str, skip: int, picking: bool) -> InlineKeyboardMarkup:
    categories = await _get_categories(token)
    page = categories[skip:skip + CATEGORY_PAGE_SIZE]
    buttons = [_category_button({"id": c.id, "name": c.name}, picking) for c in page]
    rows = _rows(buttons)
    if skip + CATEGORY_PAGE_SIZE < len(categories):
        prefix = "cm" if picking else "cat"
        rows.append([InlineKeyboardButton("Show more", callback_data=f"{prefix}:page:{skip + CATEGORY_PAGE_SIZE}")])
    return InlineKeyboardMarkup(rows)


async def category_keyboard(token: str, turn: CategoryTurn) -> InlineKeyboardMarkup | None:
    """Buttons for a category reply: Confirm/Cancel, suggestions, or a paged list."""
    if turn.needs_confirmation:
        return confirm_keyboard(turn.pending_workflow)
    picking = bool(turn.pending_workflow and turn.pending_workflow.get("intent") in CATEGORY_MANAGE_INTENTS)
    if turn.choices:
        return InlineKeyboardMarkup(_rows([_category_button(c, picking) for c in turn.choices]))
    if turn.page_from is not None:
        return await _page_keyboard(token, turn.page_from, picking)
    return None


async def _browse(message: Message, chat_id: int, session: dict[str, Any], category_id: int, skip: int) -> None:
    """Show one page of a category's products as cards (no LLM call)."""
    token = session["token"]
    category = next((c for c in await _get_categories(token) if c.id == category_id), None)
    if category is None:
        await message.reply_text("That category no longer exists.")
        return
    # No default category filter: an inherited one would retry without it and
    # show unrelated products for an empty category.
    search_tool = build_product_search_tools(token, default_filters={"skip": skip})[1]
    result = json.loads(await search_tool.ainvoke({"category": category.name}))
    if "error" in result:
        await message.reply_text(result["error"])
        return
    items = result.get("items") or []
    # Number the cards and keep their IDs and names so "the 2nd one" can be shown later.
    previous_shown = (session.get("active_context") or {}).get("shown_products") if skip else None
    shown_products = remember_shown(previous_shown, skip, shown_entries(items))
    if not items:
        answer = f'There are no products in "{category.name}" yet.'
        markup = None
    else:
        await send_product_cards(message, items, start=first_position(skip, previous_shown))
        answer = f'Products in "{category.name}" ({skip + 1}–{skip + len(items)} of {result.get("total")}).'
        markup = None
        if result.get("has_more"):
            answer += "\n\nWould you like to see more?"
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("Show more", callback_data=f"cat:browse:{category.id}:{skip + PRODUCT_PAGE_SIZE}"),
                InlineKeyboardButton("No", callback_data="products:no"),
            ]])
    recent = (session.get("conversation") or {}).get("recent_messages") or []
    recent = append_recent_message(recent, "user", f"Show {category.name} products")
    # A text follow-up such as "only Nike" refines this category's search.
    context = {
        "category": category.name, "skip": skip, "limit": PRODUCT_PAGE_SIZE,
        "has_more": bool(result.get("has_more")), "total": result.get("total"),
    }
    await save_conversation_memory(
        chat_id,
        recent_messages=append_recent_message(recent, "assistant", answer),
        pending_workflow=None,
        active_context={"intent": "PRODUCT_SEARCH", "context": context, "shown_products": shown_products},
    )
    await message.reply_text(answer, reply_markup=markup)


async def handle_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    chat = update.effective_chat
    message = update.effective_message
    if callback is None or chat is None or message is None:
        return
    await callback.answer()
    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return
    parts = callback.data.split(":")
    session = await get_session(chat.id) or {}
    if not session.get("token"):
        await message.reply_text("Your session expired. Please /login again.")
        return

    if parts[1] == "page":
        # Replace this message's buttons with the next page instead of sending a new list.
        keyboard = await _page_keyboard(session["token"], int(parts[2]), picking=parts[0] == "cm")
        try:
            await message.edit_reply_markup(reply_markup=keyboard)
        except Exception as exc:
            logger.debug("Unable to show the next category page (%s)", type(exc).__name__)
        return

    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.debug("Unable to remove the category keyboard (%s)", type(exc).__name__)

    if parts[0] == "cat":
        async with typing_indicator(context.bot, chat.id):
            await _browse(message, chat.id, session, int(parts[2]), int(parts[3]))
        return

    async with _chat_locks[chat.id]:
        session = await get_session(chat.id) or {}
        pending = session.get("pending_workflow")
        if not pending or pending.get("intent") not in CATEGORY_MANAGE_INTENTS or pending.get("waiting_for") != "category":
            await message.reply_text("That choice has expired. Please start again.")
            return
        category_id = int(parts[2])
        turn = await apply_category_pick(session["token"], pending, category_id)
        categories = await _get_categories(session["token"])
        name = next((c.name for c in categories if c.id == category_id), "category")
        recent = (session.get("conversation") or {}).get("recent_messages") or []
        recent = append_recent_message(recent, "user", f"[picked {name}]")
        await save_conversation_memory(
            chat.id,
            recent_messages=append_recent_message(recent, "assistant", turn.answer),
            pending_workflow=turn.pending_workflow,
            active_context=None,
        )
        await message.reply_text(turn.answer, reply_markup=await category_keyboard(session["token"], turn))
