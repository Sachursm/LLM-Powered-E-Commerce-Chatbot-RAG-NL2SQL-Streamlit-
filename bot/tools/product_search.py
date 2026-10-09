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
from bot.services.category_cache import cache_categories, get_cached_categories
from bot.services.safety import redact_sensitive_text

logger = logging.getLogger(__name__)

# Each product is sent to Telegram as its own photo card, so one page stays small.
PRODUCT_PAGE_SIZE = 5


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


def _singularized(tokens: list[str]) -> set[str]:
    return {token[:-1] if token.endswith("s") and len(token) > 3 else token for token in tokens}


# Connector words carry no product meaning once the category words are removed
# ("casual shoes for men" in category "Shoes" searches "casual men").
_CONNECTOR_WORDS = {"a", "an", "the", "for", "with", "and", "of", "in"}


def remove_category_terms(query: str | None, category: str | None) -> str | None:
    """Drop words already covered by the category filter; keep brand/attribute words."""
    if not query or not category:
        return query
    category_words = _singularized(_tokens(category))
    kept = [
        word for word in query.split()
        if _tokens(word)
        and not _singularized(_tokens(word)) <= category_words
        and word.casefold() not in _CONNECTOR_WORDS
    ]
    return " ".join(kept) or None


def _category_matches(phrase: str, categories: list[CategoryResponse]) -> list[CategoryResponse]:
    """The best-matching categories; several when they match equally well."""
    phrase_words = _singularized(_tokens(phrase))
    matches: list[tuple[float, int, CategoryResponse]] = []
    for category in categories:
        name_tokens = _singularized(_tokens(category.name))
        overlap = phrase_words & name_tokens
        # Match against real category names only. Half-or-better token overlap
        # handles a phrase like "keyboard" and the real category "Gaming Keyboard".
        score = len(overlap) / len(name_tokens) if name_tokens else 0.0
        if score >= 0.5:
            matches.append((score, len(overlap), category))
    if not matches:
        return []
    best = max((score, overlap) for score, overlap, _ in matches)
    return [category for score, overlap, category in matches if (score, overlap) == best]


async def _get_categories(token: str) -> list[CategoryResponse]:
    cached = await get_cached_categories()
    if cached is not None:
        return cached
    categories = await _fetch_categories(token)
    await cache_categories(categories)
    return categories


async def _fetch_categories(token: str) -> list[CategoryResponse]:
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
            # The API stores several comma-separated image URLs; one card shows the first.
            "image_url": item.image_url.split(",")[0].strip() or None,
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

    # Category matched by category_tool during this turn; product_search_tool
    # falls back to it when the model omits the category argument. A stored
    # None means the lookup ran and found no category for the new product.
    matched: dict[str, str | None] = {}

    async def _real_category(name: str) -> str | None:
        """The API's spelling of a category, or None for a name the model made up ("Shoes")."""
        try:
            categories = await _get_categories(access_token)
        except (RuntimeError, ValueError, TypeError):
            return name
        real = next((c.name for c in categories if c.name.casefold() == name.casefold()), None)
        if real is None:
            logger.info("PRODUCT_SEARCH_UNKNOWN_CATEGORY=%s; searching without a category", redact_sensitive_text(name, max_length=100))
        return real

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
        best = _category_matches(product_phrase, categories)
        if len(best) > 1:
            # Picking one would hide the others' products; search them all by text.
            matched["category"] = None
            matched["several"] = [c.name for c in best]
            logger.info("CATEGORY_TOOL_SEVERAL_MATCHES=%s", matched["several"])
            return json.dumps({
                "category": None,
                "note": "Several categories match equally; search with category=null so all of them are included.",
            })
        match = best[0] if best else None
        if match is None:
            matched["category"] = None
            return json.dumps({"category": None, "available_categories": [c.name for c in categories]})
        matched["category"] = match.name
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
        defaults = default_filters or {}
        if query_seed and (force_query_seed or not query):
            query = query_seed
        query = clean_product_search_query(query, query_seed)
        logger.info(
            "PRODUCT_SEARCH_LLM_QUERY=%s",
            redact_sensitive_text(str(llm_query) if llm_query is not None else "<null>", max_length=300),
        )
        previous_category = defaults.get("category")
        if "category" in matched:
            # This turn's lookup wins over an earlier search's category: "keyboard"
            # after a "mobile-accessories" search must not stay in that category.
            if category is None or (matched["category"] is None and category == previous_category):
                category = matched["category"]
        elif category is None:
            category = previous_category
        if category is not None and category in (matched.get("several") or []):
            # The model picked one of several equal matches; keep all of them.
            category = None
        if category is not None and category not in (matched.get("category"), previous_category):
            # Only a name the model wrote itself needs checking; this turn's
            # category_tool match and the earlier search's category are real.
            category = await _real_category(category)
        # Only a category carried over from an earlier turn may be stale.
        inherited_category = category is not None and category == previous_category and "category" not in matched
        full_query = query
        min_price = min_price if min_price is not None else defaults.get("min_price")
        max_price = max_price if max_price is not None else defaults.get("max_price")
        sort_by = sort_by if sort_by is not None else defaults.get("sort_by")
        # Active workflow pagination is application-owned machine state.
        skip = defaults.get("skip", skip if skip is not None else 0)
        limit = defaults.get("limit") or PRODUCT_PAGE_SIZE
        try:
            ProductSearchParams(
                query=redact_sensitive_text(query) if query else None,
                category=category, min_price=min_price,
                max_price=max_price, sort_by=sort_by, skip=skip, limit=limit,
            )
        except ValueError as exc:
            return json.dumps({"error": f"Invalid product search arguments: {exc}"})

        async def search(category: str | None) -> dict[str, Any]:
            # A matched category replaces the category words in the search text:
            # "Nike shoes" + category "Shoes" searches "Nike"; "clothing" + "Clothing" sends no search.
            search_query = remove_category_terms(full_query, category)
            filters = ProductSearchParams(
                query=redact_sensitive_text(search_query) if search_query else None,
                category=category, min_price=min_price,
                max_price=max_price, sort_by=sort_by, skip=skip, limit=limit,
            )
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
            result = await api_get("/products/", token=access_token, params=params)
            if result.get("status") != 200:
                return {"error": _error_for_status(int(result.get("status") or 503))}
            safe = _safe_products(result.get("data"))
            logger.info("Products returned by API: %s", len(safe["items"]))
            # The category actually applied, so the saved workflow context matches it.
            safe["category"] = category
            return safe

        try:
            safe = await search(category)
            if inherited_category and not skip and safe.get("items") == []:
                logger.info("PRODUCT_SEARCH_CATEGORY_RETRY: no results in inherited category; retrying without it")
                safe = await search(None)
            return json.dumps(safe)
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Product search failed while validating API response")
            return json.dumps({"error": "Product search is temporarily unavailable. Please try again later."})

    return [category_tool, product_search_tool]
