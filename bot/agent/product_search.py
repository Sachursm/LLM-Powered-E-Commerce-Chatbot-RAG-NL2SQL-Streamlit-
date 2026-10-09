"""LangGraph product-search workflow with bounded conversational state."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from groq import AsyncGroq
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from bot.config import settings
from bot.prompts.product_search import PRODUCT_SEARCH_SYSTEM_PROMPT
from bot.services.safety import redact_sensitive_text
from bot.tools.product_detail import build_product_detail_tool
from bot.tools.product_search import (
    PRODUCT_PAGE_SIZE,
    build_product_search_tools,
    extract_search_expression,
)

logger = logging.getLogger(__name__)


@dataclass
class ProductSearchTurn:
    answer: str
    pending_workflow: dict[str, Any] | None
    context: dict[str, Any]
    products_returned: int | None
    active_context: dict[str, Any] | None = None
    products: list[dict[str, Any]] = field(default_factory=list)
    # {"product", "category"} when the user picked one product to see in full.
    detail: dict[str, Any] | None = None


class ProductSearchState(MessagesState):
    """State for one active product-search turn; Redis persists it between turns."""

    workflow_context: dict[str, Any]
    pending_workflow: dict[str, Any] | None
    conversation_summary: str | None
    shown_products: list[dict[str, Any]]


def _system_prompt(state: ProductSearchState) -> str:
    context = state.get("workflow_context") or {}
    pending = state.get("pending_workflow") or {}
    if not context and not pending:
        return PRODUCT_SEARCH_SYSTEM_PROMPT
    compact = {
        "intent": pending.get("intent", "PRODUCT_SEARCH"),
        "waiting_for": pending.get("waiting_for"),
        "requested_information": pending.get("question"),
        "filters_and_terms": context,
    }
    return (
        PRODUCT_SEARCH_SYSTEM_PROMPT
        + "\nContinue this existing workflow using the recent messages and this compact state. "
        + "Treat the latest user message as an answer to the pending question when applicable. "
        + "For 'any kind', do not invent a type filter; for a specific reply such as 'casual', "
        + "use it as a product search term while preserving existing category and price filters. "
        + "Keep the workflow's category unless the user asks for a different kind of product; then call "
        + "category_tool again for the new product. Query holds the full product phrase including earlier terms "
        + "(e.g. previous 'Nike shoes' + 'men' -> query 'men Nike shoes'); the tool removes the category words. "
        + "For refinements such as 'for men', incorporate the phrase into query because the API has no gender filter. "
        + "For 'what about Adidas?', update the brand/query while retaining compatible category and price filters.\n"
        + "Conversation summary (for meaning only; exact filters in workflow state are authoritative): "
        + redact_sensitive_text(state.get("conversation_summary") or "", max_length=500)
        + "\nWorkflow state: "
        + json.dumps(compact, ensure_ascii=False)
        + _shown_list(state.get("shown_products") or [])
    )


def _shown_list(shown: list[dict[str, Any]]) -> str:
    """The numbered cards the user can see, so "the 2nd one" maps to a Product ID."""
    if not shown:
        return ""
    lines = [f"{n}. Product ID {entry['id']}: {entry.get('name') or ''}" for n, entry in enumerate(shown, start=1)]
    return "\nProducts shown to the user (list number. Product ID: name):\n" + "\n".join(lines)


def _to_groq_messages(messages: list[BaseMessage], system_prompt: str) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if isinstance(message, HumanMessage):
            converted.append({"role": "user", "content": redact_sensitive_text(str(message.content))})
        elif isinstance(message, ToolMessage):
            converted.append({
                "role": "tool", "tool_call_id": message.tool_call_id,
                # A page of product JSON is longer than the default chat-text limit.
                "content": redact_sensitive_text(str(message.content), max_length=8000),
            })
        elif isinstance(message, AIMessage):
            item: dict[str, Any] = {
                "role": "assistant",
                "content": redact_sensitive_text(str(message.content)) if message.content else None,
            }
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": redact_sensitive_text(json.dumps(call["args"])),
                        },
                    }
                    for call in message.tool_calls
                ]
            converted.append(item)
    return converted


def _tool_definitions(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item.name,
                "description": item.description,
                "parameters": item.args_schema.model_json_schema(),
            },
        }
        for item in tools
    ]


def _build_graph(tools: list[Any], groq_client: Any):
    async def assistant(state: ProductSearchState) -> dict[str, Any]:
        response = await groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=_to_groq_messages(state["messages"], _system_prompt(state)),
            tools=_tool_definitions(tools),
            tool_choice="auto",
            temperature=0,
        )
        choice = response.choices[0].message
        calls = []
        for call in choice.tool_calls or []:
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    args = {}
            except (TypeError, json.JSONDecodeError):
                args = {}
            calls.append({"name": call.function.name, "args": args, "id": call.id, "type": "tool_call"})
        return {"messages": [AIMessage(content=choice.content or "", tool_calls=calls)]}

    def route_after_assistant(state: ProductSearchState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    graph = StateGraph(ProductSearchState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "assistant")
    graph.add_conditional_edges("assistant", route_after_assistant, {"tools": "tools", END: END})
    graph.add_edge("tools", "assistant")
    return graph.compile()


def _initial_context(
    query: str,
    pending: dict[str, Any] | None,
    active: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prior = pending or active or {}
    context = dict(prior.get("context") or {})
    if context.get("query"):
        # Normalize legacy sessions too: older contexts may contain the full
        # request sentence rather than the product-identifying search phrase.
        normalized_query = extract_search_expression(str(context["query"]))
        context["query"] = redact_sensitive_text(normalized_query, max_length=200) if normalized_query else None
    if not prior:
        expression = extract_search_expression(query)
        context["query"] = redact_sensitive_text(expression, max_length=200) if expression else None
    elif pending and pending.get("waiting_for") in {"product_type", "category"}:
        reply = extract_search_expression(query)
        # An answer to "What kind?" is a few words ("casual", "gaming"). A whole
        # sentence is not appended, or the query collects unrelated requests.
        if (
            reply
            and len(reply.split()) <= 4
            and reply.casefold() not in {"any kind", "any type", "anything", "whatever"}
        ):
            previous_query = str(context.get("query") or "").strip()
            category = str(context.get("category") or "").replace("-", " ").strip()
            if previous_query and reply.casefold() in previous_query.casefold():
                merged_query = reply
            elif category and category.casefold() in previous_query.casefold():
                brand_or_terms = re.sub(re.escape(category), "", previous_query, flags=re.IGNORECASE).strip()
                merged_query = " ".join(part for part in (brand_or_terms, reply, category) if part)
            elif previous_query and previous_query.casefold() in reply.casefold():
                merged_query = reply
            elif previous_query:
                merged_query = f"{reply} {previous_query}"
            else:
                merged_query = reply
            context["query"] = redact_sensitive_text(merged_query, max_length=200)
    match = re.search(
        r"\b(?:under|below|less than|up to|upto|at most)\s*(?:₹|rs\.?\s*)?([\d,]+)",
        query,
        flags=re.IGNORECASE,
    )
    if match:
        context["max_price"] = int(match.group(1).replace(",", ""))
    match = re.search(
        r"\b(?:above|over|more than|at least)\s*(?:₹|rs\.?\s*)?([\d,]+)",
        query,
        flags=re.IGNORECASE,
    )
    if match:
        context["min_price"] = int(match.group(1).replace(",", ""))
    return context


def _collect_tool_state(
    messages: list[BaseMessage],
    context: dict[str, Any],
    *,
    query_seed: str | None = None,
    force_query_seed: bool = False,
) -> tuple[dict[str, Any], bool, int | None, list[dict[str, Any]]]:
    result_context = dict(context)
    searched = False
    products_returned: int | None = None
    products: list[dict[str, Any]] = []
    tool_messages = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            response = tool_messages.get(call["id"])
            if not response:
                continue
            try:
                payload = json.loads(str(response.content))
            except (TypeError, json.JSONDecodeError):
                continue
            if call["name"] == "category_tool":
                if payload.get("category"):
                    result_context["category"] = payload["category"]
                elif "category" in payload:
                    # No category for the new product: drop the previous search's category.
                    result_context.pop("category", None)
            elif call["name"] == "product_search_tool":
                searched = True
                args = call.get("args") or {}
                for key in ("query", "category", "min_price", "max_price", "sort_by", "skip", "limit"):
                    if args.get(key) is not None:
                        value = args[key]
                        result_context[key] = (
                            redact_sensitive_text(value, max_length=200)
                            if isinstance(value, str)
                            else value
                        )
                if force_query_seed and query_seed:
                    result_context["query"] = query_seed
                if "category" in payload:
                    # The tool reports the category it actually applied (it may have
                    # dropped a stale one), which overrides the model's argument.
                    if payload["category"]:
                        result_context["category"] = payload["category"]
                    else:
                        result_context.pop("category", None)
                items = payload.get("items")
                if isinstance(items, list):
                    products_returned = len(items)
                    products = [item for item in items if isinstance(item, dict)]
                for key in ("has_more", "total", "skip", "limit"):
                    if key in payload:
                        result_context[key] = payload[key]
    return result_context, searched, products_returned, products


def _waiting_for(answer: str) -> str | None:
    lowered = answer.casefold()
    if "?" not in answer:
        return None
    if re.search(r"\b(kind|type)\b", lowered):
        return "product_type"
    if "brand" in lowered:
        return "brand"
    if "category" in lowered:
        return "category"
    if "price" in lowered or "budget" in lowered:
        return "price_range"
    return "clarification"


def _fallback_answer(searched: bool, product_count: int | None, context: dict[str, Any]) -> str:
    if searched and product_count:
        return "Here's what I found."
    if searched:
        query = context.get("query")
        return f"No products found for {query}. Would you like to try a different search?" if query else (
            "No products found. Would you like to try a different search?"
        )
    return "What product are you looking for?"


def _messages_from_history(history: list[dict[str, str]] | None, query: str) -> list[BaseMessage]:
    source = list(history or [])[-8:]
    if not source or source[-1].get("role") != "user" or source[-1].get("content") != query:
        source.append({"role": "user", "content": query})
    messages: list[BaseMessage] = []
    for item in source:
        content = item.get("content")
        if not isinstance(content, str):
            continue
        if item.get("role") == "assistant":
            messages.append(AIMessage(content=redact_sensitive_text(content)))
        elif item.get("role") == "user":
            messages.append(HumanMessage(content=redact_sensitive_text(content)))
    return messages


# Words that only ask for further results of the current search, e.g.
# "is there any other bra" or "do you have more?".
_MORE_WORDS = {"other", "others", "another", "more", "else"}
_MORE_FILLER = {
    "is", "are", "there", "do", "you", "have", "any", "anything", "something", "some",
    "show", "see", "get", "give", "me", "please", "ones", "one", "options", "option",
    "results", "products", "items", "available", "got", "the", "a", "an",
}


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _is_more_request(
    query: str,
    history: list[dict[str, str]] | None,
    product_query: str | None = None,
) -> bool:
    # "show me more about the 8th one" asks for one product's details, not the next page.
    if re.search(
        r"\b(show|see|get|give)\s+(me\s+)?more\b(?!\s+(?:about|of|on|details?|info|information)\b)"
        r"|\bmore\s+(options|results)\b",
        query, re.I,
    ):
        return True
    words = re.findall(r"[a-z]+", query.casefold())
    if _MORE_WORDS & set(words):
        # Anything besides filler and the current product words is a refinement:
        # "any other bra" asks for more, "any other brand" or "other colors" does not.
        product_words = {_singular(w) for w in re.findall(r"[a-z]+", (product_query or "").casefold())}
        leftover = [w for w in words if w not in _MORE_WORDS | _MORE_FILLER and _singular(w) not in product_words]
        if not leftover:
            return True
    if re.fullmatch(r"\s*(yes|yeah|yep|sure|okay|ok)\s*[.!]?\s*", query, re.I):
        prior = list(history or [])[:-1]
        assistant = next((m.get("content", "") for m in reversed(prior) if m.get("role") == "assistant"), "")
        return bool(re.search(r"\b(more|another|additional)\b", assistant, re.I))
    return False


async def run_product_search_turn(
    query: str,
    access_token: str,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    pending_workflow: dict[str, Any] | None = None,
    active_context: dict[str, Any] | None = None,
    conversation_summary: str | None = None,
    shown_products: list[dict[str, Any]] | None = None,
    groq_client: Any | None = None,
) -> ProductSearchTurn:
    """Run one graph turn, keeping credentials outside all graph/model state.

    ``shown_products`` is the numbered list on the user's cards, so the model can
    open "the 2nd one" with product_detail_tool.
    """
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    previous = pending_workflow or active_context
    context = _initial_context(query, pending_workflow, active_context)
    if previous:
        # A changed/refined search starts at page one. Explicit more-results
        # replies advance from the backend's retained page state.
        previous_skip = int(context.get("skip") or 0)
        wants_more = _is_more_request(query, recent_messages, context.get("query"))
        if wants_more and "has_more" in context and not context["has_more"]:
            # The last page was already shown; restarting at page one would
            # repeat products the user has seen. Answer without an LLM call.
            product = context.get("query")
            answer = (
                f"No more products found for {product}. Would you like to try a different search?"
                if product else "No more products found. Would you like to try a different search?"
            )
            logger.info("PRODUCT_SEARCH_NO_MORE_RESULTS=true")
            if own_client:
                await client.close()
            return ProductSearchTurn(answer, None, context, 0, {"intent": "PRODUCT_SEARCH", "context": context})
        context["skip"] = 0
        if context.get("has_more") and wants_more:
            context["skip"] = previous_skip + int(context.get("limit") or PRODUCT_PAGE_SIZE)
    try:
        query_seed = context.get("query") or extract_search_expression(query)
        force_query_seed = previous is None or bool(
            pending_workflow and pending_workflow.get("waiting_for") in {"product_type", "category"}
        )
        tools = build_product_search_tools(
            access_token,
            query_seed=query_seed,
            force_query_seed=force_query_seed,
            default_filters=context if previous is not None else None,
        )
        detail: dict[str, Any] = {}
        tools.append(build_product_detail_tool(access_token, detail))
        graph = _build_graph(tools, client)
        result = await graph.ainvoke(
            {
                "messages": _messages_from_history(recent_messages, query),
                "workflow_context": context,
                "pending_workflow": pending_workflow,
                "conversation_summary": conversation_summary,
                "shown_products": shown_products or [],
            },
            config={"recursion_limit": 12},
        )
        messages = result["messages"]
        final = messages[-1]
        answer = redact_sensitive_text(str(final.content))
        context, searched, product_count, products = _collect_tool_state(
            messages,
            context,
            query_seed=query_seed,
            force_query_seed=force_query_seed,
        )
        if not answer.strip():
            # The model sometimes ends with empty content after a search, since the
            # cards already show the products; Telegram rejects empty messages.
            answer = "Here are the full details." if detail else _fallback_answer(searched, product_count, context)
        # A product's details answer the user; a closing question there is not a clarification.
        waiting = _waiting_for(answer) if not searched and not detail else None
        if waiting:
            pending = {
                "intent": "PRODUCT_SEARCH",
                "initial_query": (previous or {}).get("initial_query") or redact_sensitive_text(query, max_length=400),
                "context": context,
                "waiting_for": waiting,
                "question": redact_sensitive_text(answer, max_length=300),
            }
        else:
            pending = None
        active = {"intent": "PRODUCT_SEARCH", "context": context} if context else None
        logger.info("Tool called: product_search_tool=%s", searched)
        logger.info("Products returned: %s", product_count if product_count is not None else "not searched")
        logger.info("Pending workflow after response: %s", pending.get("waiting_for") if pending else "none")
        logger.info("ACTIVE_CONTEXT=%s", redact_sensitive_text(json.dumps(context, ensure_ascii=False)))
        return ProductSearchTurn(answer, pending, context, product_count, active, products, detail or None)
    finally:
        if own_client:
            await client.close()


async def run_product_search(
    query: str,
    access_token: str,
    *,
    groq_client: Any | None = None,
) -> str:
    """Backward-compatible string-returning entry point used by Phase 1 tests."""
    result = await run_product_search_turn(query, access_token, groq_client=groq_client)
    return result.answer
