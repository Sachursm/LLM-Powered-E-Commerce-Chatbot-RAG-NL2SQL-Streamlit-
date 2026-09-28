"""Start, help, and logout commands."""

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.session import (
    delete_session,
    get_session,
    is_logged_in,
)


def _chat_id(update: Update) -> int | None:
    return update.effective_chat.id if update.effective_chat else None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    message = update.effective_message
    if chat_id is None or message is None:
        return

    if await is_logged_in(chat_id):
        session = await get_session(chat_id) or {}
        username = session.get("username", "there")
        role = session.get("role", "USER")
        await message.reply_text(
            f"Welcome back, {username}! ({role})\nHow can I help you?"
        )
    else:
        await message.reply_text(
            "Welcome to SachuMart!\n\n/login - Login\n/register - Create account"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    message = update.effective_message
    if chat_id is None or message is None:
        return

    if not await is_logged_in(chat_id):
        await message.reply_text(
            "Available commands:\n/login - Login\n/register - Create account"
        )
        return

    session = await get_session(chat_id) or {}
    role = session.get("role", "USER")
    help_text = (
        "Available commands:\n/logout - Log out\n/help - Show this help\n"
        "Ask me anything about products, orders, and your account."
    )
    if role == "SELLER":
        help_text += "\nYou can manage your orders and products."
    elif role == "ADMIN":
        help_text += "\nYou have admin access."
    elif role == "HUB_MANAGER":
        help_text += "\nYou have delivery hub manager access."
    elif role == "DELIVERY_AGENT":
        help_text += "\nYou have delivery agent access."

    await message.reply_text(help_text)


async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    message = update.effective_message
    if chat_id is None or message is None:
        return

    if not await is_logged_in(chat_id):
        await message.reply_text("You are not logged in.")
        return

    session = await get_session(chat_id) or {}
    username = session.get("username", "there")
    await delete_session(chat_id)
    await message.reply_text(
        f"Goodbye, {username}! You have been logged out."
    )
