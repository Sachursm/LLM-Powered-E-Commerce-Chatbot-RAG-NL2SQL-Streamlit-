"""LLM intent fallback for low-confidence semantic-router results."""

import logging
import json
import re
from typing import Any

from groq import AsyncGroq

from bot.config import settings
from bot.router.semantic import allowed_intents_for_role
from bot.services.safety import redact_sensitive_text

logger = logging.getLogger(__name__)


def _recent_context(messages: list[dict[str, str]] | None) -> list[dict[str, str]]:
    safe_messages = []
    for item in (messages or [])[-6:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            safe_messages.append({"role": role, "content": redact_sensitive_text(content, max_length=500)})
    return safe_messages


async def resolve_fallback_intent(
    query: str,
    role: str | None,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    groq_client: Any | None = None,
) -> str:
    """Ask Groq to disambiguate UNKNOWN; validate its answer against role candidates."""
    candidates = allowed_intents_for_role(role)
    prompt = (
        "Classify the latest user message into exactly one allowed high-level intent. "
        "PRODUCT_SEARCH means browsing/availability/filtering products. FAQ means a "
        "policy or service question. GENERAL_CHAT means greetings or casual chat. "
        "Use UNKNOWN if no allowed intent fits. Do not choose tools, infer permissions, "
        "or answer the user. Return only the intent label.\n"
        f"Allowed intents: {', '.join(candidates)}, UNKNOWN.\n"
        f"Recent context (may be empty): {_recent_context(recent_messages)!r}\n"
        f"Latest message: {redact_sensitive_text(query)!r}"
    )
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        response = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You classify intent only. Do not authorize users or select tools.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=24,
            # A single intent label needs little reasoning. Product-search calls
            # keep the default effort because they choose the search filters.
            reasoning_effort="low",
        )
        raw = response.choices[0].message.content or ""
        decision = raw.strip().strip("`\"' ").upper()
        if decision.startswith("{"):
            import json

            try:
                decision = str(json.loads(decision).get("intent", "UNKNOWN")).upper()
            except (ValueError, AttributeError):
                decision = "UNKNOWN"
        elif decision not in candidates and decision != "UNKNOWN":
            labels = {label for label in candidates} | {"UNKNOWN"}
            match = re.search(r"\b(" + "|".join(sorted(labels, key=len, reverse=True)) + r")\b", decision)
            decision = match.group(1) if match else "UNKNOWN"
        if decision not in candidates and decision != "UNKNOWN":
            decision = "UNKNOWN"
        logger.info("LLM decision after router fallback: %s", decision)
        return decision
    finally:
        if own_client:
            await client.close()


# Every action the bot can run. Words like "remove", "add" and "change" appear
# in several actions, so the detector compares actions, not words.
TASK_DESCRIPTIONS = {
    "PRODUCT_SEARCH": "search or browse products (product type, brand, gender, color, size, price, rating, sorting, "
                      "more results), including opening one product from the shown list",
    "PRODUCT_DETAIL": "show the full details of one product by its Product ID when no product list is shown",
    "PRODUCT_CREATE": "create a new product listing (name, description, price, stock, category, photo)",
    "PRODUCT_UPDATE": "change an existing product (which product; new name, description, price, stock, category, or photo)",
    "PRODUCT_DELETE": "delete a product listing (which product)",
    "CATEGORY": "list the store's categories or find one by name",
    "CATEGORY_CREATE": "create a new product category (its name)",
    "CATEGORY_UPDATE": "rename a product category (which category, its new name)",
    "CATEGORY_DELETE": "delete a product category (which category)",
    "CART": "view the shopping cart, add products to it, change their quantities, remove them, or empty it",
}
_OTHER_ACTIONS = "orders and checkout, payments, returns, reviews, the account, or store policy questions"

# Replies that stay in the current action, including ones whose words another action also uses.
SAME_ACTION_EXAMPLES = {
    "PRODUCT_SEARCH": "'for men', 'under 3000', 'only Adidas', 'remove Nike' (drops a filter), "
                      "'add black' (adds a filter), 'change it to under 2000', 'sort by price', 'show more', "
                      "'the second one', 'select the second one give me data about it', 'tell me more about "
                      "product 21' (opens one product from the shown list)",
    "PRODUCT_DETAIL": "'2', 'the first one', '812', 'product id 455'",
    "PRODUCT_CREATE": "'price 4999', 'stock 20', 'category shoes', 'change the name to Puma Runner X', 'yes'",
    "PRODUCT_UPDATE": "'25', 'the blue one', 'price 2999', 'also set stock to 5', 'change the category too'",
    "PRODUCT_DELETE": "'45', 'the Leather Jacket', 'the second one', 'yes'",
    "CATEGORY": "'footwear', 'bags', 'something like jewellery', 'show more'",
    "CATEGORY_CREATE": "'Gadgets', 'call it Winter Wear', 'make it Smart Home instead'",
    "CATEGORY_UPDATE": "'shoes', 'to Footwear', 'call it Apparel instead'",
    "CATEGORY_DELETE": "'test1', 'the Toys one', 'Luggage'",
    "CART": "'remove the 2nd one', 'make it 3', 'the blue shirt', 'add one more', 'also add product 25', "
            "'empty it', 'yes'",
}
# Commands for another action that look like the current one.
DIFFERENT_ACTION_EXAMPLES = {
    "PRODUCT_SEARCH": "'remove test1 from categories' (delete a category), 'add a category called Gadgets' "
                      "(create a category), 'change the price of product 25' (change a product), "
                      "'delete product 45' (delete a product), 'what categories do you have' (list categories), "
                      "'add the 2nd one to my cart' (the cart), 'remove product 10 from my cart' (the cart)",
    "PRODUCT_DETAIL": "'show me sandals' (search), 'only under 1000' (search), 'delete product 812' "
                      "(delete a product), 'change the price of product 812' (change a product), "
                      "'add it to my cart' (the cart)",
    "PRODUCT_CREATE": "'delete product 45' (delete a product), 'update product 25' (change a product), "
                      "'add a category called Gadgets' (create a category), 'show me shoes' (search)",
    "PRODUCT_UPDATE": "'delete product 25' (delete a product), 'add a new product' (create a product), "
                      "'rename category shoes to footwear' (rename a category), 'show me shoes under 3000' (search)",
    "PRODUCT_DELETE": "'delete category Toys' (delete a category), 'change the price of product 45' "
                      "(change a product), 'show me shoes' (search)",
    "CATEGORY": "'remove test1 from categories' (delete a category), 'add category Footwear' (create a category), "
                "'rename category shoes to footwear' (rename a category), 'show me Nike shoes under 3000' (search)",
    "CATEGORY_CREATE": "'delete category Toys' (delete a category), 'rename category shoes' (rename a category), "
                       "'add a new product' (create a product), 'what categories do you have' (list categories)",
    "CATEGORY_UPDATE": "'delete category Toys' (delete a category), 'add category Footwear' (create a category), "
                       "'change the price of product 25' (change a product)",
    "CATEGORY_DELETE": "'delete product 45' (delete a product), 'rename category shoes' (rename a category), "
                       "'show me shoes' (search)",
    "CART": "'show me Nike shoes' (search), 'checkout my cart' (orders), 'delete product 45' (delete a product), "
            "'tell me about product 25' (product details)",
}


def _continuation_instructions(current_task: str | None) -> str:
    task = TASK_DESCRIPTIONS.get(current_task or "")
    if task is None:
        return (
            "Determine whether the current user message continues or depends on the previous "
            "exchange. Judge it using the previous user and assistant messages; do not "
            "treat the current message as a standalone query or decide whether it is complete "
            "by itself. A short reply that plausibly answers a question or clarification in "
            "the previous assistant response is a continuation. Refinements, added constraints, "
            "confirmations, and references to the previous response also continue it. A clearly "
            "unrelated request does not. "
        )
    actions = "\n".join(f"- {description}" for description in TASK_DESCRIPTIONS.values())
    return (
        f"The assistant can do these actions:\n{actions}\n- {_OTHER_ACTIONS}\n"
        f"The current action is: {task}.\n"
        "Work out which action the current user message asks for, using the previous exchange. "
        "Answer YES only when it is the SAME action as the current one: it refines or adjusts it, "
        "answers the question the assistant asked, confirms, or asks for more, even when it is "
        "very short. Answer NO when it asks for a DIFFERENT action, even when it uses the same "
        "words (remove, add, change, delete) or mentions something from the previous exchange. "
        "Answer NO for a clearly unrelated request.\n"
        f"Same action (YES): {SAME_ACTION_EXAMPLES[current_task]}.\n"
        f"Different action (NO): {DIFFERENT_ACTION_EXAMPLES[current_task]}.\n"
    )


async def detect_continuation(
    query: str,
    previous_user_message: str | None,
    previous_bot_message: str | None,
    *,
    current_task: str | None = None,
    groq_client: Any | None = None,
) -> str:
    """Return strict YES/NO for whether a user message continues the current task.

    ``current_task`` is the active workflow's intent. This detector only
    compares actions; it does not choose tools, answer, or authorize. Invalid model output
    fails closed to NO.
    """
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    prompt = (
        _continuation_instructions(current_task)
        + "Do not generate a query, choose a tool, or answer the user. Return ONLY YES or NO.\n"
        f"Previous user message: {redact_sensitive_text(previous_user_message or '', max_length=500)}\n"
        f"Previous assistant response: {redact_sensitive_text(previous_bot_message or '', max_length=500)}\n"
        f"Current user message: {redact_sensitive_text(query, max_length=500)}"
    )
    # Temporary diagnostics for identifying whether bad decisions come from
    # stale/missing conversation state, the configured model, or its output.
    # Redaction and length limits keep credentials and oversized text out of logs.
    logger.info(
        "CONTINUATION_PREVIOUS_USER=%s",
        redact_sensitive_text(previous_user_message or "", max_length=500),
    )
    logger.info(
        "CONTINUATION_PREVIOUS_BOT=%s",
        redact_sensitive_text(previous_bot_message or "", max_length=500),
    )
    logger.info("CONTINUATION_CURRENT=%s", redact_sensitive_text(query, max_length=500))
    logger.info("CONTINUATION_TASK=%s", current_task or "<none>")
    logger.info("CONTINUATION_MODEL=%s", settings.CONTINUATION_MODEL)
    try:
        response = await client.chat.completions.create(
            model=settings.CONTINUATION_MODEL,
            messages=[
                {"role": "system", "content": "Classify conversation continuation only. Return exactly YES or NO. Do not select tools, answer, call APIs, or authorize actions."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            # Reasoning models may consume a small token budget before emitting
            # their final YES/NO text. Leave enough room for the final answer.
            max_tokens=128,
            # YES/NO needs little reasoning; see resolve_fallback_intent.
            reasoning_effort="low",
        )
        raw_output = response.choices[0].message.content or ""
        logger.info(
            "CONTINUATION_RAW_OUTPUT=%s",
            redact_sensitive_text(raw_output, max_length=200),
        )
        normalized = raw_output.strip().upper()
        decision = normalized if normalized in {"YES", "NO"} else "NO"
        if decision == "NO" and normalized not in {"NO", ""}:
            logger.warning("Continuation detector returned invalid output; treating as NO")
        logger.info("CONTINUATION_PARSED_RESULT=%s", decision)
        logger.info("CONTINUATION_CHECK=%s", decision)
        return decision
    except Exception as exc:
        logger.warning("Continuation detector unavailable (%s); treating as NO", type(exc).__name__)
        logger.info("CONTINUATION_CHECK=NO")
        return "NO"
    finally:
        if own_client:
            await client.close()


# Backward-compatible name for callers/tests from the earlier routing flow.
async def resolve_active_context_action(
    query: str,
    role: str | None,
    active_context: dict[str, Any],
    *,
    recent_messages: list[dict[str, str]] | None = None,
    groq_client: Any | None = None,
) -> str:
    history = _recent_context(recent_messages)
    previous_user = next((m["content"] for m in reversed(history) if m["role"] == "user" and m["content"] != query), None)
    previous_assistant = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), None)
    result = await detect_continuation(
        query, previous_user, previous_assistant, groq_client=groq_client,
    )
    return "CONTINUE" if result == "YES" else "NEW_REQUEST"
