"""Create/update product tools backed by the existing FastAPI product endpoints.

The LLM only fills a draft through these tools. Nothing is written to the API
until the user taps Confirm; ``submit_product_change`` performs that write with
the API's own ``ProductCreate`` / ``ProductUpdate`` schemas.
"""

import json
import logging
import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.category import CategoryResponse
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from bot.services.api_client import api_get, api_patch, api_post
from bot.services.category_match import closest_categories, find_exact
from bot.services.safety import redact_sensitive_text
from bot.tools.product_search import _get_categories

logger = logging.getLogger(__name__)

# Admins write through /products/, sellers through /seller/products/; both
# endpoints take the same ProductCreate / ProductUpdate bodies.
PRODUCT_ENDPOINTS = {"ADMIN": "/products/", "SELLER": "/seller/products/"}

REQUIRED_CREATE_FIELDS = ("name", "description", "price", "stock", "category", "image_url")
FIELD_LABELS = {
    "name": "product name",
    "description": "description",
    "price": "price",
    "stock": "stock quantity",
    "category": "category",
    "image_url": "a product photo (send it here) or an image URL",
}
_MAX_MATCHES = 8
AUTO_PICK_SIMILARITY = 0.80


class ProductFieldsInput(BaseModel):
    """Product fields the user stated in this message; omit anything not mentioned."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Product name")
    description: str | None = Field(default=None, description="Product description")
    price: float | None = Field(default=None, description="Price in rupees, greater than 0")
    stock: int | None = Field(default=None, description="Units in stock, 0 or more")
    category: str | None = Field(default=None, description="Category name as the user said it")
    image_url: str | None = Field(default=None, description="An http(s) image URL the user pasted")


class CreateProductInput(ProductFieldsInput):
    """Fields for a new product (mirrors app.schemas.product.ProductCreate)."""


class UpdateProductInput(ProductFieldsInput):
    """Fields to change on an existing product (mirrors ProductUpdate)."""

    product_id: int | None = Field(default=None, description="Product ID, if the user gave one")
    product_name: str | None = Field(
        default=None, description="Name of the product to change, if the user gave a name and no ID"
    )


def endpoint_for_role(role: str | None) -> str | None:
    return PRODUCT_ENDPOINTS.get((role or "").strip().upper())


def split_image_urls(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def add_image_url(draft: dict[str, Any], url: str) -> int:
    """Append one image to the draft (the API stores comma-separated URLs)."""
    urls = split_image_urls(draft.get("image_url"))
    if url not in urls:
        urls.append(url)
    draft["image_url"] = ",".join(urls)
    return len(urls)


def missing_create_fields(draft: dict[str, Any]) -> list[str]:
    return [name for name in REQUIRED_CREATE_FIELDS if draft.get(name) in (None, "")]


def _format_price(value: Any) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"₹{price:,.0f}" if price.is_integer() else f"₹{price:,.2f}"


def _clean_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate model-supplied values; return accepted fields and user-facing problems."""
    accepted: dict[str, Any] = {}
    problems: list[str] = []
    for key in ("name", "description", "category"):
        value = fields.get(key)
        if value is None:
            continue
        text = redact_sensitive_text(str(value), max_length=2000).strip()
        if not text:
            problems.append(f"The {FIELD_LABELS[key]} can't be empty.")
        elif key == "name" and len(text) > 200:
            problems.append("The product name must be 200 characters or fewer.")
        else:
            accepted[key] = text
    if fields.get("price") is not None:
        if fields["price"] <= 0:
            problems.append("The price must be greater than 0.")
        else:
            accepted["price"] = float(fields["price"])
    if fields.get("stock") is not None:
        if fields["stock"] < 0:
            problems.append("The stock quantity can't be negative.")
        else:
            accepted["stock"] = int(fields["stock"])
    if fields.get("image_url") is not None:
        urls = split_image_urls(str(fields["image_url"]))
        if urls and all(re.match(r"^https?://\S+$", url) for url in urls):
            accepted["image_url"] = urls
        else:
            problems.append("The image URL must start with http:// or https://.")
    return accepted, problems


async def resolve_category(token: str, name: str) -> tuple[str | None, list[str]]:
    """Return the exact API category name for a phrase, or the closest names for errors."""
    categories: list[CategoryResponse] = await _get_categories(token)
    exact = find_exact(name, categories)
    if exact is not None:
        return exact.name, []
    # The catalog has around a hundred categories, so suggest the closest in
    # meaning ("footwear" → the shoe categories) instead of listing them all.
    close = await closest_categories(name, categories)
    if len(close) == 1 and close[0][1] >= AUTO_PICK_SIMILARITY:
        # One clear winner ("tshirt" → "tshirts"); "shoes" with casual-, formal-
        # and sports-shoes is ambiguous and is asked instead.
        return close[0][0].name, []
    return None, [category.name for category, _ in close]


def category_not_found_message(category: str, closest: list[str]) -> str:
    message = f'Category "{category}" not found.'
    if closest:
        return message + " The closest are: " + ", ".join(closest) + ". Which one should I use?"
    return message + ' Which category should I use? Say "show categories" to see them all.'



def _error_for_status(status: int, detail: str) -> str:
    if status == 401:
        return "Your session may have expired. Please /login again."
    if status == 403:
        return "You don't have permission to manage products."
    if status == 400 and detail:
        return detail.rstrip(".") + "."
    if status == 422:
        return "The API didn't accept those product details. Please check them and try again."
    if status == 429:
        return "Too many requests right now. Please try again shortly."
    return "Product changes are temporarily unavailable. Please try again later."


def _detail(result: dict[str, Any]) -> str:
    data = result.get("data")
    detail = data.get("detail") if isinstance(data, dict) else None
    return detail if isinstance(detail, str) else ""


async def _owned_products(token: str, role: str) -> list[ProductResponse] | None:
    """Products a seller may edit; ``None`` for admins, who may edit any product."""
    if role != "SELLER":
        return None
    result = await api_get("/seller/products/", token=token)
    if result.get("status") != 200 or not isinstance(result.get("data"), list):
        raise RuntimeError(_error_for_status(int(result.get("status") or 503), _detail(result)))
    return [ProductResponse.model_validate(item) for item in result["data"]]


async def _find_product(token: str, role: str, product_id: int) -> ProductResponse | None:
    owned = await _owned_products(token, role)
    if owned is not None:
        return next((item for item in owned if item.id == product_id), None)
    result = await api_get(f"/products/{product_id}", token=token)
    if result.get("status") == 404:
        return None
    if result.get("status") != 200:
        raise RuntimeError(_error_for_status(int(result.get("status") or 503), _detail(result)))
    return ProductResponse.model_validate(result.get("data"))


def _name_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


async def _search_products(token: str, role: str, name: str) -> list[ProductResponse]:
    owned = await _owned_products(token, role)
    if owned is None:
        result = await api_get("/products/", token=token, params={"search": name, "limit": _MAX_MATCHES})
        if result.get("status") != 200:
            raise RuntimeError(_error_for_status(int(result.get("status") or 503), _detail(result)))
        items = (result.get("data") or {}).get("items") or []
        return [ProductResponse.model_validate(item) for item in items][:_MAX_MATCHES]
    wanted = _name_tokens(name)
    exact = [item for item in owned if item.name.casefold() == name.casefold()]
    if exact:
        return exact
    return [item for item in owned if wanted and wanted <= _name_tokens(item.name)][:_MAX_MATCHES]


def _current_values(product: ProductResponse, categories: list[CategoryResponse]) -> dict[str, Any]:
    category = next((c.name for c in categories if c.id == product.category_id), None)
    return {
        "name": product.name,
        "description": redact_sensitive_text(product.description, max_length=300),
        "price": product.price,
        "stock": product.stock,
        "category": category,
        "image_count": len(split_image_urls(product.image_url)),
    }


def build_product_manage_tools(
    access_token: str,
    role: str,
    state: dict[str, Any],
) -> list[Any]:
    """Build per-turn tools that edit ``state`` (the draft); the JWT never reaches the model.

    ``state`` holds ``draft``, ``product_id`` and ``current`` from earlier turns.
    The tools set ``status`` plus details the agent turns into the reply.
    """
    if not access_token:
        raise ValueError("An authenticated API session is required")
    draft: dict[str, Any] = state.setdefault("draft", {})

    async def merge_fields(fields: dict[str, Any]) -> bool:
        """Merge validated fields into the draft; return False when the reply is an error."""
        accepted, problems = _clean_fields(fields)
        if problems:
            state.update(status="invalid", problems=problems)
            return False
        for url in accepted.pop("image_url", []):
            add_image_url(draft, url)
        if "category" in accepted:
            requested = accepted.pop("category")
            category, available = await resolve_category(access_token, requested)
            if category is None:
                # Keep everything else; the user only needs to name a real category.
                draft.update(accepted)
                draft.pop("category", None)
                state.update(status="category_not_found", category=requested, available=available)
                return False
            draft["category"] = category
        draft.update(accepted)
        return True

    @tool("create_product_tool", args_schema=CreateProductInput)
    async def create_product_tool(**fields: Any) -> str:
        """Add the product details from the user's message to the new-product draft."""
        logger.info("Tool called: create_product_tool fields=%s", sorted(k for k, v in fields.items() if v is not None))
        try:
            if await merge_fields(fields):
                missing = missing_create_fields(draft)
                state.update(status="missing_fields" if missing else "ready", missing=missing)
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Product draft validation failed")
            state.update(status="error", error="Categories are temporarily unavailable. Please try again.")
        return json.dumps({key: state.get(key) for key in ("status", "missing", "problems")})

    @tool("update_product_tool", args_schema=UpdateProductInput)
    async def update_product_tool(
        product_id: int | None = None,
        product_name: str | None = None,
        **fields: Any,
    ) -> str:
        """Choose the product to change and add the requested changes to the update draft."""
        logger.info(
            "Tool called: update_product_tool product_id=%s by_name=%s fields=%s",
            product_id, bool(product_name), sorted(k for k, v in fields.items() if v is not None),
        )
        try:
            if not await merge_fields(fields):
                return json.dumps({"status": state["status"]})
            if product_id is None and product_name and not state.get("product_id"):
                matches = await _search_products(access_token, role, redact_sensitive_text(product_name, max_length=200))
                if len(matches) == 1:
                    product_id = matches[0].id
                else:
                    state.update(
                        status="choose_product",
                        product_name=redact_sensitive_text(product_name, max_length=200),
                        matches=[{"id": m.id, "name": m.name, "price": m.price} for m in matches],
                    )
                    return json.dumps({"status": state["status"], "matches": len(matches)})
            if product_id is not None and product_id != state.get("product_id"):
                product = await _find_product(access_token, role, product_id)
                if product is None:
                    state.update(status="product_not_found", requested_id=product_id)
                    return json.dumps({"status": state["status"]})
                categories = await _get_categories(access_token)
                state.update(product_id=product.id, current=_current_values(product, categories))
            if not state.get("product_id"):
                state["status"] = "need_product"
            elif not draft:
                state["status"] = "need_changes"
            else:
                state["status"] = "ready"
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning("Product update lookup failed (%s)", type(exc).__name__)
            message = str(exc) if isinstance(exc, RuntimeError) else ""
            state.update(status="error", error=message or "Product lookup is temporarily unavailable. Please try again.")
        return json.dumps({"status": state["status"]})

    return [create_product_tool, update_product_tool]


def describe_update_changes(draft: dict[str, Any], current: dict[str, Any]) -> list[str]:
    lines = []
    for key, label in (("name", "Name"), ("description", "Description"), ("price", "Price"),
                       ("stock", "Stock"), ("category", "Category")):
        if key not in draft:
            continue
        new = draft[key]
        old = current.get(key)
        if key == "price":
            new, old = _format_price(new), _format_price(old) if old is not None else None
        if key == "description":
            new = str(new)[:300]
            lines.append(f"{label}: {new}")
        else:
            lines.append(f"{label}: {old} → {new}" if old is not None else f"{label}: {new}")
    if draft.get("image_url"):
        count = len(split_image_urls(draft["image_url"]))
        lines.append(f"Images: {count} new (replaces the current {current.get('image_count', 0)})")
    return lines


def confirmation_summary(intent: str, pending: dict[str, Any]) -> str:
    draft = pending.get("draft") or {}
    if intent == "PRODUCT_CREATE":
        return "\n".join([
            "Please confirm the new product:",
            f"Name: {draft.get('name')}",
            f"Description: {str(draft.get('description') or '')[:300]}",
            f"Price: {_format_price(draft.get('price'))}",
            f"Stock: {draft.get('stock')}",
            f"Category: {draft.get('category')}",
            f"Images: {len(split_image_urls(draft.get('image_url')))}",
            "",
            "Tap Confirm to create it, or Cancel.",
        ])
    current = pending.get("current") or {}
    return "\n".join([
        f"Please confirm the changes to product #{pending.get('product_id')} ({current.get('name')}):",
        *describe_update_changes(draft, current),
        "",
        "Tap Confirm to save them, or Cancel.",
    ])


async def submit_product_change(
    access_token: str,
    role: str | None,
    pending: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Write a confirmed draft to the API; return the reply and any still-open draft."""
    intent = pending.get("intent")
    base = endpoint_for_role(role)
    if base is None:
        return "You don't have permission to manage products.", None
    draft = dict(pending.get("draft") or {})
    try:
        if intent == "PRODUCT_CREATE":
            payload = ProductCreate.model_validate(draft).model_dump(exclude_none=True)
            logger.info("PRODUCT_CREATE_SUBMIT endpoint=%s", base)
            result = await api_post(base, data=payload, token=access_token)
        elif intent == "PRODUCT_UPDATE" and pending.get("product_id"):
            payload = ProductUpdate.model_validate(draft).model_dump(exclude_unset=True)
            endpoint = f"{base.rstrip('/')}/{int(pending['product_id'])}"
            logger.info("PRODUCT_UPDATE_SUBMIT endpoint=%s fields=%s", endpoint, sorted(payload))
            result = await api_patch(endpoint, data=payload, token=access_token)
        else:
            return "That product change is no longer active. Please start again.", None
    except ValidationError:
        return "Some product details are missing or invalid. Please start again.", None

    status = int(result.get("status") or 503)
    detail = _detail(result)
    if status in (200, 201):
        data = result.get("data") or {}
        name = data.get("name") or draft.get("name") or "the product"
        if intent == "PRODUCT_CREATE":
            return f"✅ Created product #{data.get('id')}: {name}.", None
        return f"✅ Updated product #{data.get('id', pending.get('product_id'))}: {name}.", None
    if status == 404 and detail.casefold().startswith("category not found"):
        # The category disappeared after the draft was checked; keep the draft open.
        category = draft.get("category") or ""
        try:
            _, available = await resolve_category(access_token, category)
        except (RuntimeError, ValueError, TypeError):
            available = []
        draft.pop("category", None)
        reopened = {**pending, "draft": draft, "waiting_for": "fields", "confirm_id": None}
        return category_not_found_message(category, available), reopened
    if status == 404:
        return f"Product #{pending.get('product_id')} isn't in your listings.", None
    logger.warning("Product change rejected (status=%s)", status)
    return _error_for_status(status, detail), None
