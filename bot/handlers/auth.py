"""Login and registration conversation handlers."""

import logging
from typing import Any

import jwt
from telegram import Update
from telegram.ext import ContextTypes

from bot.services.api_client import api_login, api_register
from bot.services.session import (
    delete_session,
    get_session,
    is_logged_in,
    set_session,
    update_session,
)

logger = logging.getLogger(__name__)


def _chat_id(update: Update) -> int | None:
    return update.effective_chat.id if update.effective_chat else None


def _api_error(data: Any) -> str:
    if isinstance(data, dict):
        detail = data.get("detail", "Unknown error")
        if isinstance(detail, str):
            return detail
    return "Unknown error"


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    if chat_id is None or update.effective_message is None:
        return
    if await is_logged_in(chat_id):
        await update.effective_message.reply_text(
            "Already logged in. Use /logout first."
        )
        return
    await set_session(chat_id, {"state": "WAITING_LOGIN_USERNAME"})
    await update.effective_message.reply_text("Enter your username:")


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _chat_id(update)
    if chat_id is None or update.effective_message is None:
        return
    if await is_logged_in(chat_id):
        await update.effective_message.reply_text(
            "Already logged in. Use /logout first."
        )
        return
    await set_session(chat_id, {"state": "WAITING_REGISTER_USERNAME"})
    await update.effective_message.reply_text("Choose a username:")


async def handle_auth_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Process the next login/register input; return whether it was consumed."""
    chat_id = _chat_id(update)
    message = update.effective_message
    if chat_id is None or message is None or not message.text:
        return False

    session = await get_session(chat_id)
    state = session.get("state") if session else None
    if not isinstance(state, str) or not state.startswith("WAITING_"):
        return False

    value = message.text.strip()
    if state == "WAITING_LOGIN_USERNAME":
        if not value:
            await message.reply_text("Username cannot be empty. Enter your username:")
            return True
        await update_session(
            chat_id,
            username=value,
            state="WAITING_LOGIN_PASSWORD",
        )
        await message.reply_text("Enter your password:")
        return True

    if state == "WAITING_LOGIN_PASSWORD":
        username = session.get("username")
        if not isinstance(username, str):
            await delete_session(chat_id)
            await message.reply_text("Login flow expired. Try /login again.")
            return True
        result = await api_login(username, message.text)
        data = result.get("data", {})
        if result.get("status") == 200 and isinstance(data, dict):
            token = data.get("access_token")
            try:
                claims = jwt.decode(
                    token,
                    options={"verify_signature": False},
                    algorithms=["HS256"],
                )
                role = claims.get("role")
                if not isinstance(token, str) or not isinstance(role, str):
                    raise ValueError("Token is missing required claims")
            except (jwt.InvalidTokenError, TypeError, ValueError):
                await delete_session(chat_id)
                await message.reply_text(
                    "Login failed: the API returned an invalid token. Try /login again."
                )
                return True

            await set_session(
                chat_id,
                {
                    "token": token,
                    "username": username,
                    "role": role,
                    "state": "LOGGED_IN",
                },
            )
            logger.info("[LOGIN] %s logged in as %s", username, role)
            await message.reply_text(
                f"Login successful! Welcome, {username} ({role})"
            )
        else:
            error = _api_error(data)
            await delete_session(chat_id)
            await message.reply_text(
                f"Login failed: {error}. Try /login again."
            )
        return True

    if state == "WAITING_REGISTER_USERNAME":
        if not value:
            await message.reply_text("Username cannot be empty. Choose a username:")
            return True
        await update_session(
            chat_id,
            username=value,
            state="WAITING_REGISTER_EMAIL",
        )
        await message.reply_text("Enter your email:")
        return True

    if state == "WAITING_REGISTER_EMAIL":
        if not value:
            await message.reply_text("Email cannot be empty. Enter your email:")
            return True
        await update_session(
            chat_id,
            email=value,
            state="WAITING_REGISTER_PASSWORD",
        )
        await message.reply_text("Choose a password:")
        return True

    if state == "WAITING_REGISTER_PASSWORD":
        username = session.get("username")
        email = session.get("email")
        if not isinstance(username, str) or not isinstance(email, str):
            await delete_session(chat_id)
            await message.reply_text("Registration flow expired. Try /register again.")
            return True

        result = await api_register(username, email, message.text)
        if result.get("status") == 201:
            await delete_session(chat_id)
            logger.info("[REGISTER] new user created: %s", username)
            await message.reply_text("Account created! Use /login to sign in.")
        else:
            error = _api_error(result.get("data", {}))
            await delete_session(chat_id)
            await message.reply_text(
                f"Registration failed: {error}. Try /register again."
            )
        return True

    # An unrecognized WAITING_* state is not a flow this handler can consume.
    return False
