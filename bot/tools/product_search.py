"""Product and category lookup tools backed by the existing FastAPI APIs."""

import json
import logging
import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.category import CategoryResponse
from app.schemas.pagination import PaginatedResponse
from app.schemas.product import ProductResponse
from bot.services.api_client import api_get
from bot.services.safety import redact_sensitive_text

logger = logging.getLogger(__name__)


class CategoryLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_phrase: str = Field(description="Product phrase whose category should be identified")


class ProductSearchParams(BaseModel):
    """LLM-facing filters; ``query`` is mapped to the API's ``search`` field."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, description="Brand or product terms, excluding category and price wording")
    category: str | None = Field(default=None, description="Exact existing category name")
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    sort_by: str | None = Field(default=None, description="price_low, price_high, rating, or name")
    skip: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_filters(self) -> "ProductSearchParams":
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price cannot exceed max_price")
        if self.sort_by not in {None, "price_low", "price_high", "rating", "name"}:
            raise ValueError("sort_by must be price_low, price_high, rating, or name")
        if self.query is not None and not self.query.strip():
            raise ValueError("query cannot be blank")
        return self


def _error_for_status(status: int) -> str:
    messages = {
        400: "The search filters were not accepted. Please adjust the search.",
        401: "Your session may have expired. Please sign in again.",
        403: "You do not have permission to access these results.",
        404: "The requested resource was not found.",
        429: "Search is temporarily rate limited. Please try again shortly.",
    }
    if status in messages:
        return messages[status]
    if status in {500, 502, 503, 504} or status >= 500:
        return "Product search is temporarily unavailable. Please try again later."
    return "The API could not complete the request. Please try again."


def _payload(result: dict[str, Any], model: type[BaseModel]) -> Any:
    status = result.get("status")
    if status != 200:
        raise RuntimeError(_error_for_status(int(status or 503)))
    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError("Invalid API response")
    return model.model_validate(data)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def extract_search_expression(text: str) -> str | None:
    """Remove request framing and price constraints, retaining product wording."""
    expression = text.strip()
    expression = re.sub(
        r"^(?:(?:what products are available|what products do you have|what are the|what do you have|are there|do you have|do you sell|have you got|have you|can i see|show me|show|find|search for|browse|i am looking for|i'm looking for|i am searching for|i'm searching for|looking for|look for|i want|i need)\s+)",
        "", expression, flags=re.IGNORECASE,
    )
    expression = re.sub(
        r"\b(?:no\s+preferences?|any\s+(?:kind|type)|whatever\s+you\s+have|show\s+me\s+all|show\s+me\s+more|show\s+more|what\s+do\s+you\s+have|what\s+are\s+the|which\s+ones|is\s+there|do\s+you\s+have|show\s+me|i\s+am\s+looking\s+for\s+(?:a|an|the)?|i'm\s+looking\s+for\s+(?:a|an|the)?|looking\s+for\s+(?:a|an|the)?|i\s+want|i\s+need)\b",
        " ", expression, flags=re.IGNORECASE,
    )
    expression = re.sub(r"^(?:any|some|a|an|the)\s+", "", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\b(?:rupees?|rs\.?|inr)\b", "", expression, flags=re.IGNORECASE)
    expression = re.sub(
        r"\b(?:under|below|less than|up to|upto|at most|above|over|more than|at least)\s*(?:₹|rs\.?\s*)?[\d,]+\b",
        "", expression, flags=re.IGNORECASE,
    )
    expression = re.sub(r"\b(?:cheap|expensive|best|top\s+rated)\b", " ", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\b(?:show\s+more|next\s+page|next)\b", " ", expression, flags=re.IGNORECASE)
    expression = re.sub(r"[?,!;:]", " ", expression)
    expression = re.sub(r"\bproducts?\b", "", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\s+", " ", expression).strip(" .,!?;:")
    return expression or None


_KEEP_EXISTING_QUERY = re.compile(
    r"\b(?:no\s+preferences?|any\s+(?:kind|type)|whatever\s+you\s+have|show\s+me\s+all|show\s+me\s+more|show\s+more|next)\b",
    re.IGNORECASE,
)
_QUERY_FILLER = re.compile(
    r"\b(?:no\s+preferences?|what\s+do\s+you\s+have|what\s+are\s+the|which\s+ones|is\s+there|do\s+you\s+have|show\s+me|i\s+am\s+looking\s+for\s+(?:a|an|the)?|i'm\s+looking\s+for\s+(?:a|an|the)?|looking\s+for\s+(?:a|an|the)?|i\s+want|i\s+need)\b",
    re.IGNORECASE,
)


def clean_product_search_query(query: str | None, query_seed: str | None = None) -> str | None:
    """Remove conversational wording before using a model-supplied search query."""
    seed = extract_search_expression(query_seed) if query_seed else None
    if not query:
        return seed

    raw = redact_sensitive_text(query, max_length=500).strip()
    if _KEEP_EXISTING_QUERY.search(raw):
        return seed

    cleaned = extract_search_expression(raw)
    if cleaned is None:
        return seed

    # If the model emitted a long sentence containing conversational filler,
    # prefer the already validated workflow query over guessing product nouns.
    if len(_tokens(cleaned)) > 5 and _QUERY_FILLER.search(raw) and seed:
        return seed
    return cleaned


def _category_match(phrase: str, categories: list[CategoryResponse]) -> CategoryResponse | None:
    def singularized(tokens: list[str]) -> set[str]:
        return {token[:-1] if token.endswith("s") and len(token) > 3 else token for token in tokens}

    phrase_words = singularized(_tokens(phrase))
    matches: list[tuple[float, int, CategoryResponse]] = []
    for category in categories:
        name_tokens = singularized(_tokens(category.name))
        overlap = phrase_words & name_tokens
        # Match against real category names only. Half-or-better token overlap
        # handles a phrase like "keyboard" and the real category "Gaming Keyboard".
        score = len(overlap) / len(name_tokens) if name_tokens else 0.0
        if score >= 0.5:
            matches.append((score, len(overlap), category))
    return max(matches, key=lambda item: (item[0], item[1]))[2] if matches else None


async def _get_categories(token: str) -> list[CategoryResponse]:
    categories: list[CategoryResponse] = []
    skip = 0
    while skip < 1000:
        # The token stays in this tool execution layer. It is never an LLM argument/result.
        result = await api_get("/categories/", token=token, params={"skip": skip, "limit": 100})
        page = _payload(result, PaginatedResponse[CategoryResponse])
        categories.extend(page.items)
        if not page.has_more or not page.items:
            break
        skip += page.limit
    return categories


def _safe_products(data: Any) -> dict[str, Any]:
    page = PaginatedResponse[ProductResponse].model_validate(data)
    products = [
        {
            "id": item.id,
            "name": redact_sensitive_text(item.name, max_length=200),
            "description": redact_sensitive_text(item.description, max_length=400),
            "price": item.price,
            "stock": item.stock,
            "rating": item.rating,
            "ratings_count": item.ratings_count,
            "image_url": item.image_url,
            "category_id": item.category_id,
            "seller_id": item.seller_id,
        }
        for item in page.items
    ]
    return {"items": products, "total": page.total, "skip": page.skip, "limit": page.limit, "has_more": page.has_more}


def build_product_search_tools(
    access_token: str,
    *,
    query_seed: str | None = None,
    force_query_seed: bool = False,
    default_filters: dict[str, Any] | None = None,
) -> list[Any]:
    """Build per-request tools; the JWT is captured privately and never exposed to the model."""
    if not access_token:
        raise ValueError("An authenticated API session is required")

    @tool("category_tool", args_schema=CategoryLookupInput)
    async def category_tool(product_phrase: str) -> str:
        """Match a product phrase to an exact category returned by the marketplace API."""
        product_phrase = redact_sensitive_text(product_phrase)
        logger.info("Tool called: category_tool arguments=%s", product_phrase)
        try:
            categories = await _get_categories(access_token)
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Category lookup failed while validating API response")
            return json.dumps({"error": "Categories are temporarily unavailable."})
        match = _category_match(product_phrase, categories)
        if match is None:
            return json.dumps({"category": None, "available_categories": [c.name for c in categories]})
        return json.dumps({"category": match.name})

    @tool("product_search_tool", args_schema=ProductSearchParams)
    async def product_search_tool(
        query: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        sort_by: str | None = None,
        skip: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Search actual marketplace products with validated structured filters."""
        llm_query = query
        # The category lookup is a separate filter. Preserve the initial user
        # expression as the API search term even if the model only sends a category.
        defaults = default_filters or {}
        if query_seed and (force_query_seed or not query):
            query = query_seed
        query = clean_product_search_query(query, query_seed)
        logger.info(
            "PRODUCT_SEARCH_LLM_QUERY=%s",
            redact_sensitive_text(str(llm_query) if llm_query is not None else "<null>", max_length=300),
        )
        category = category if category is not None else defaults.get("category")
        min_price = min_price if min_price is not None else defaults.get("min_price")
        max_price = max_price if max_price is not None else defaults.get("max_price")
        sort_by = sort_by if sort_by is not None else defaults.get("sort_by")
        # Active workflow pagination is application-owned machine state.
        skip = defaults.get("skip", skip if skip is not None else 0)
        limit = defaults.get("limit", limit if limit is not None else 20)
        try:
            filters = ProductSearchParams(
                query=redact_sensitive_text(query) if query else None,
                category=category, min_price=min_price,
                max_price=max_price, sort_by=sort_by, skip=skip, limit=limit,
            )
        except ValueError as exc:
            return json.dumps({"error": f"Invalid product search arguments: {exc}"})
        params: dict[str, Any] = {"skip": filters.skip, "limit": filters.limit}
        if filters.query:
            params["search"] = filters.query.strip()
        for name in ("category", "min_price", "max_price", "sort_by"):
            value = getattr(filters, name)
            if value is not None:
                params[name] = value
        logger.info(
            "PRODUCT_SEARCH_API_QUERY=%s",
            redact_sensitive_text(str(params.get("search")) if params.get("search") is not None else "<null>", max_length=300),
        )
        logger.info("Tool called: product_search_tool arguments=%s", redact_sensitive_text(json.dumps(params)))
        try:
            result = await api_get("/products/", token=access_token, params=params)
            if result.get("status") != 200:
                return json.dumps({"error": _error_for_status(int(result.get("status") or 503))})
            safe = _safe_products(result.get("data"))
            logger.info("Products returned by API: %s", len(safe["items"]))
            return json.dumps(safe)
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Product search failed while validating API response")
            return json.dumps({"error": "Product search is temporarily unavailable. Please try again later."})

    return [category_tool, product_search_tool]
