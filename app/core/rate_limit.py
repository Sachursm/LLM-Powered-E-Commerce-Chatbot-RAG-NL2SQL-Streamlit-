"""Shared SlowAPI limiter backed by Redis."""

import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def get_user_key(request: Request) -> str:
    """Use the authenticated user ID, falling back to the client IP."""
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            if payload.get("sub") is not None:
                return f"user:{payload['sub']}"
        except jwt.InvalidTokenError:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=get_user_key,
    storage_uri=settings.REDIS_URL,
    # Routes currently return regular Python values and don't accept a
    # Starlette Response parameter, so SlowAPI cannot inject limit headers.
    # Rate-limit enforcement and 429 handling remain enabled without headers.
    headers_enabled=False,
    strategy="fixed-window",
)
