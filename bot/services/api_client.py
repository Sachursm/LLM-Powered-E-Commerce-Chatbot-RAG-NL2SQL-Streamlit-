"""Async HTTP client helpers for the FastAPI e-commerce API."""

import logging
from typing import Any

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)


async def _request(
    method: str,
    endpoint: str,
    *,
    data: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    token: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{settings.API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}"} if token else None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                json=data,
                data=form,
                headers=headers,
                params=params,
            )
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text or "Invalid API response"}
        return {"status": response.status_code, "data": body}
    except httpx.RequestError as exc:
        logger.warning("API request failed (%s %s): %s", method, endpoint, exc)
        return {"status": 503, "data": {"detail": "API unavailable"}}


async def api_login(username: str, password: str) -> dict[str, Any]:
    """Authenticate through the API's OAuth2 form endpoint."""
    return await _request(
        "POST",
        "/auth/login",
        form={"username": username, "password": password},
    )


async def api_register(
    username: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    """Register a standard USER account through the JSON API."""
    return await _request(
        "POST",
        "/auth/register",
        data={"username": username, "email": email, "password": password},
    )


async def api_get(
    endpoint: str,
    token: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _request("GET", endpoint, token=token, params=params)


async def api_post(
    endpoint: str,
    data: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    return await _request("POST", endpoint, data=data, token=token)


async def api_patch(
    endpoint: str,
    data: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    return await _request("PATCH", endpoint, data=data, token=token)


async def api_delete(
    endpoint: str,
    token: str | None = None,
) -> dict[str, Any]:
    return await _request("DELETE", endpoint, token=token)
