"""Keep Telegram's "typing…" indicator visible while the bot works on a reply."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from telegram import Bot
from telegram.constants import ChatAction
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# Telegram clears a chat action after about 5 seconds, so it is re-sent before then.
_REFRESH_SECONDS = 4


async def _keep_typing(bot: Bot, chat_id: int) -> None:
    while True:
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except TelegramError as exc:
            logger.debug("Unable to send typing action (%s)", type(exc).__name__)
        await asyncio.sleep(_REFRESH_SECONDS)


@contextlib.asynccontextmanager
async def typing_indicator(bot: Bot, chat_id: int) -> AsyncIterator[None]:
    task = asyncio.create_task(_keep_typing(bot, chat_id))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
