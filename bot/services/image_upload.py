"""Upload product photos to Cloudinary and return a permanent public URL.

Telegram's own file links embed the bot token and expire, so they must never be
stored as a product image_url.
"""

import hashlib
import logging
import time

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

# Cloudinary's free plan rejects images above 10 MB.
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class ImageUploadError(Exception):
    """A user-safe reason the photo could not be stored."""


def image_upload_configured() -> bool:
    return bool(
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    )


def _signature(params: dict[str, str], api_secret: str) -> str:
    # Cloudinary signs the alphabetically sorted upload parameters plus the secret.
    payload = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1(f"{payload}{api_secret}".encode()).hexdigest()


async def upload_product_image(data: bytes, *, content_type: str = "image/jpeg") -> str:
    """Store one image and return its https URL."""
    if not image_upload_configured():
        raise ImageUploadError("Photo upload isn't set up yet. Please send an image URL instead.")
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ImageUploadError("Please send a JPEG, PNG, or WebP image.")
    if not data:
        raise ImageUploadError("That photo was empty. Please send it again.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageUploadError("That photo is larger than 10 MB. Please send a smaller one.")

    params = {"folder": settings.CLOUDINARY_FOLDER, "timestamp": str(int(time.time()))}
    form = {
        **params,
        "api_key": settings.CLOUDINARY_API_KEY,
        "signature": _signature(params, settings.CLOUDINARY_API_SECRET),
    }
    url = f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url, data=form, files={"file": ("product", data, content_type)}
            )
    except httpx.RequestError as exc:
        logger.warning("Cloudinary upload failed (%s)", type(exc).__name__)
        raise ImageUploadError("Photo upload is temporarily unavailable. Please try again.") from exc

    if response.status_code != 200:
        # The body may echo request details; log only the status.
        logger.warning("Cloudinary upload rejected (status=%s)", response.status_code)
        raise ImageUploadError("The photo could not be uploaded. Please try another image.")
    try:
        secure_url = response.json().get("secure_url")
    except ValueError:
        secure_url = None
    if not isinstance(secure_url, str) or not secure_url.startswith("https://"):
        raise ImageUploadError("The photo could not be uploaded. Please try another image.")
    logger.info("PRODUCT_IMAGE_UPLOADED=true")
    return secure_url
