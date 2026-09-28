"""Authentication check used by text-message handling."""

from telegram import Update

from bot.services.session import is_logged_in


async def user_is_authenticated(update: Update) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    return await is_logged_in(chat.id)
