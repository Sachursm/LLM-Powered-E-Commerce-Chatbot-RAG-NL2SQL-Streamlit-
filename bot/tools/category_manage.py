"""Category view helpers and create/update/delete tools backed by the categories API.

As with products, the LLM only fills a draft. ``submit_category_change`` writes
to the API with its ``CategoryCreate`` / ``CategoryUpdate`` schemas after the
user taps Confirm.
"""

import json
import logging
import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from bot.services.api_client import api_delete, api_get, api_patch, api_post
from bot.services.category_match import DUPLICATE_SIMILARITY, closest_categories, find_exact
from bot.services.safety import redact_sensitive_text
from bot.tools.product_search import _get_categories

logger = logging.getLogger(__name__)

CATEGORY_ENDPOINT = "/categories/"
CATEGORY_MANAGE_INTENTS = frozenset({"CATEGORY_CREATE", "CATEGORY_UPDATE", "CATEGORY_DELETE"})
_MAX_NAME_LENGTH = 100

# Words that frame a category request but never name a category.
_VIEW_FILLER = re.compile(
    r"\b(?:what|which|show|list|see|view|display|browse|me|all|the|a|an|any|of|your|you|do|does|"
    r"have|has|there|is|are|available|categories|category|sections?|store|shop|in|like|similar|"
    r"to|called|named|can|i|please|for|products?|items?|kinds?|types?|we|give|tell|about|our|"
    r"sell|get|other|more|some|options?|look|looking|search|searching|find|want|need)\b",
    re.IGNORECASE,
)


def extract_category_phrase(text: str) -> str | None:
    """Return the category wording in a view request ("categories like footwear" → "footwear")."""
    phrase = _VIEW_FILLER.sub(" ", redact_sensitive_text(text, max_length=300))
    phrase = re.sub(r"[^\w\s-]", " ", phrase)
    phrase = " ".join(phrase.split())
    return phrase or None


def category_ref(category: CategoryResponse) -> dict[str, Any]:
    return {"id": category.id, "name": category.name}


class CreateCategoryInput(BaseModel):
    """Name for a new category (mirrors app.schemas.category.CategoryCreate)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Name of the new category, as the user wrote it")


class UpdateCategoryInput(BaseModel):
    """Category to rename and its new name (mirrors CategoryUpdate)."""

    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, description="Existing category the user wants to rename")
    new_name: str | None = Field(default=None, description="The new name for that category")


class DeleteCategoryInput(BaseModel):
    """Category the user wants to delete."""

    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, description="Existing category the user wants to delete")


def _clean_name(value: str | None) -> tuple[str | None, str | None]:
    """Return (name, problem) for a model-supplied category name."""
    if value is None:
        return None, None
    name = " ".join(redact_sensitive_text(str(value), max_length=500).split())
    if not name:
        return None, "The category name can't be empty."
    if len(name) > _MAX_NAME_LENGTH:
        return None, f"The category name must be {_MAX_NAME_LENGTH} characters or fewer."
    return name, None


async def product_count(token: str, category_name: str) -> int:
    """How many products use a category (the API refuses to delete one in use)."""
    result = await api_get(
        "/products/", token=token, params={"category": category_name, "skip": 0, "limit": 1}
    )
    if result.get("status") != 200 or not isinstance(result.get("data"), dict):
        raise RuntimeError("Categories are temporarily unavailable. Please try again.")
    return int(result["data"].get("total") or 0)


async def choose_category(token: str, state: dict[str, Any], category: CategoryResponse) -> None:
    """Record the category an update/delete applies to and decide the next step."""
    draft = state.setdefault("draft", {})
    draft["category"] = category_ref(category)
    intent = state["intent"]
    if intent == "CATEGORY_DELETE":
        count = await product_count(token, category.name)
        if count:
            state.update(status="in_use", count=count)
        else:
            state["status"] = "ready"
        return
    new_name = draft.get("new_name")
    if not new_name:
        state["status"] = "need_new_name"
    elif find_exact(new_name, [category]) is not None:
        draft.pop("new_name", None)
        state.update(status="same_name")
    else:
        categories = await _get_categories(token)
        taken = find_exact(new_name, [c for c in categories if c.id != category.id])
        if taken is not None:
            draft.pop("new_name", None)
            state.update(status="name_taken", taken=taken.name)
        else:
            state["status"] = "ready"


async def _resolve_existing(token: str, state: dict[str, Any], phrase: str) -> None:
    categories = await _get_categories(token)
    exact = find_exact(phrase, categories)
    if exact is not None:
        await choose_category(token, state, exact)
        return
    close = await closest_categories(phrase, categories)
    state.update(
        status="category_not_found",
        requested=phrase,
        suggestions=[category_ref(c) for c, _ in close],
    )


def build_category_manage_tools(access_token: str, state: dict[str, Any]) -> list[Any]:
    """Per-turn tools that edit ``state`` (the draft); the JWT never reaches the model."""
    if not access_token:
        raise ValueError("An authenticated API session is required")
    draft: dict[str, Any] = state.setdefault("draft", {})

    def failed(problem: str) -> str:
        state.update(status="invalid", problem=problem)
        return json.dumps({"status": "invalid"})

    @tool("create_category_tool", args_schema=CreateCategoryInput)
    async def create_category_tool(name: str | None = None) -> str:
        """Set the name of the new category the user wants to create."""
        logger.info("Tool called: create_category_tool has_name=%s", bool(name))
        name, problem = _clean_name(name)
        if problem:
            return failed(problem)
        if name:
            draft["name"] = name
        if not draft.get("name"):
            state["status"] = "need_name"
            return json.dumps({"status": "need_name"})
        try:
            categories = await _get_categories(access_token)
            existing = find_exact(draft["name"], categories)
            if existing is not None:
                state.update(status="exists", existing=existing.name)
            else:
                similar = await closest_categories(
                    draft["name"], categories, limit=3, min_similarity=DUPLICATE_SIMILARITY
                )
                draft["similar"] = [c.name for c, _ in similar]
                state["status"] = "ready"
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Category lookup failed for create")
            state.update(status="error", error="Categories are temporarily unavailable. Please try again.")
        return json.dumps({"status": state["status"]})

    @tool("update_category_tool", args_schema=UpdateCategoryInput)
    async def update_category_tool(category: str | None = None, new_name: str | None = None) -> str:
        """Choose the category to rename and set its new name."""
        logger.info("Tool called: update_category_tool has_category=%s has_new_name=%s", bool(category), bool(new_name))
        category, problem = _clean_name(category)
        new_name, new_problem = _clean_name(new_name)
        if problem or new_problem:
            return failed(problem or new_problem)
        if new_name:
            draft["new_name"] = new_name
        try:
            if category:
                await _resolve_existing(access_token, state, category)
            elif draft.get("category"):
                chosen = CategoryResponse.model_validate(draft["category"])
                await choose_category(access_token, state, chosen)
            else:
                state["status"] = "need_category"
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Category lookup failed for update")
            state.update(status="error", error="Categories are temporarily unavailable. Please try again.")
        return json.dumps({"status": state["status"]})

    @tool("delete_category_tool", args_schema=DeleteCategoryInput)
    async def delete_category_tool(category: str | None = None) -> str:
        """Choose the category the user wants to delete."""
        logger.info("Tool called: delete_category_tool has_category=%s", bool(category))
        category, problem = _clean_name(category)
        if problem:
            return failed(problem)
        try:
            if category:
                await _resolve_existing(access_token, state, category)
            elif draft.get("category"):
                await choose_category(access_token, state, CategoryResponse.model_validate(draft["category"]))
            else:
                state["status"] = "need_category"
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.warning("Category lookup failed for delete (%s)", type(exc).__name__)
            state.update(status="error", error="Categories are temporarily unavailable. Please try again.")
        return json.dumps({"status": state["status"]})

    return [create_category_tool, update_category_tool, delete_category_tool]


def confirmation_summary(intent: str, pending: dict[str, Any]) -> str:
    draft = pending.get("draft") or {}
    if intent == "CATEGORY_CREATE":
        lines = [f'Create a new category "{draft.get("name")}"?']
        if draft.get("similar"):
            lines.append("Similar categories already exist: " + ", ".join(draft["similar"]) + ".")
    elif intent == "CATEGORY_UPDATE":
        lines = [f'Rename category "{(draft.get("category") or {}).get("name")}" → "{draft.get("new_name")}"?',
                 "Products in this category keep it under the new name."]
    else:
        lines = [f'Delete category "{(draft.get("category") or {}).get("name")}"? No products use it.']
    return "\n".join([*lines, "", "Tap Confirm to continue, or Cancel."])


def _detail(result: dict[str, Any]) -> str:
    data = result.get("data")
    detail = data.get("detail") if isinstance(data, dict) else None
    return detail if isinstance(detail, str) else ""


def _error_for_status(status: int) -> str:
    if status == 401:
        return "Your session may have expired. Please /login again."
    if status == 403:
        return "You don't have permission to manage categories."
    if status == 429:
        return "Too many requests right now. Please try again shortly."
    return "Category changes are temporarily unavailable. Please try again later."


async def submit_category_change(
    access_token: str,
    role: str | None,
    pending: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Write a confirmed category draft; return the reply and any still-open draft."""
    intent = pending.get("intent")
    draft = pending.get("draft") or {}
    category = draft.get("category") or {}
    try:
        if intent == "CATEGORY_CREATE":
            payload = CategoryCreate.model_validate({"name": draft.get("name")}).model_dump()
            logger.info("CATEGORY_CREATE_SUBMIT")
            result = await api_post(CATEGORY_ENDPOINT, data=payload, token=access_token)
        elif intent == "CATEGORY_UPDATE" and category.get("id"):
            payload = CategoryUpdate.model_validate({"name": draft.get("new_name")}).model_dump()
            logger.info("CATEGORY_UPDATE_SUBMIT category_id=%s", category["id"])
            result = await api_patch(f"{CATEGORY_ENDPOINT}{int(category['id'])}", data=payload, token=access_token)
        elif intent == "CATEGORY_DELETE" and category.get("id"):
            logger.info("CATEGORY_DELETE_SUBMIT category_id=%s", category["id"])
            result = await api_delete(f"{CATEGORY_ENDPOINT}{int(category['id'])}", token=access_token)
        else:
            return "That category change is no longer active. Please start again.", None
    except ValidationError:
        return "The category name is missing. Please start again.", None

    status = int(result.get("status") or 503)
    detail = _detail(result).casefold()
    old, new = category.get("name"), draft.get("new_name")
    if status in (200, 201, 204):
        if intent == "CATEGORY_CREATE":
            return f'✅ Created category "{(result.get("data") or {}).get("name") or draft.get("name")}".', None
        if intent == "CATEGORY_UPDATE":
            return f'✅ Renamed category "{old}" → "{new}".', None
        return f'✅ Deleted category "{old}".', None
    if status == 409 and intent == "CATEGORY_CREATE":
        return f'Category "{draft.get("name")}" already exists.', None
    if status == 409 and intent == "CATEGORY_UPDATE":
        return f'A category named "{new}" already exists. Pick another name.', {
            **pending, "draft": {**draft, "new_name": None}, "waiting_for": "new_name", "confirm_id": None,
        }
    if status == 409 and "products" in detail:
        return f'Can\'t delete "{old}" because products are using it. Move them to another category first.', None
    if status == 404:
        return f'Category "{old}" no longer exists.', None
    logger.warning("Category change rejected (status=%s)", status)
    return _error_for_status(status), None
