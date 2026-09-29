"""Local semantic intent classification for the Telegram bot."""

from typing import Any


def classify_intent(text: str) -> dict[str, Any]:
    """Classify text without importing or initializing the model until needed."""
    from bot.router.semantic import classify_intent as _classify_intent

    return _classify_intent(text)


__all__ = ["classify_intent"]
