"""Telegram bot process entry point: ``python -m bot.main``."""

import logging

from telegram import Update
from telegram.ext import (
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
from bot.middleware.auth_check import user_is_authenticated

logger = logging.getLogger(__name__)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    if await handle_auth_flow(update, context):
        return

    if not await user_is_authenticated(update):
        await message.reply_text("Please /login or /register first.")
        return

    await message.reply_text("I heard you! LLM coming soon.")


def build_application() -> Application:
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("logout", logout_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    return application


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger.info("Starting SachuMart Telegram bot")
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
