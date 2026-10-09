"""LangGraph workflow that fills a product create/update/delete draft for confirmation."""

import json
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any

from groq import AsyncGroq
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from bot.agent.product_search import _messages_from_history, _to_groq_messages, _tool_definitions
from bot.config import settings
from bot.prompts.product_manage import (
    PRODUCT_CREATE_SYSTEM_PROMPT,
    PRODUCT_DELETE_SYSTEM_PROMPT,
    PRODUCT_UPDATE_SYSTEM_PROMPT,
)
from bot.services.safety import redact_sensitive_text
from bot.tools.product_manage import (
    FIELD_LABELS,
    build_product_manage_tools,
    category_not_found_message,
    confirmation_summary,
    split_image_urls,
    _format_price,
)

logger = logging.getLogger(__name__)

PRODUCT_MANAGE_INTENTS = frozenset({"PRODUCT_CREATE", "PRODUCT_UPDATE", "PRODUCT_DELETE"})
_PROMPTS = {
    "PRODUCT_CREATE": PRODUCT_CREATE_SYSTEM_PROMPT,
    "PRODUCT_UPDATE": PRODUCT_UPDATE_SYSTEM_PROMPT,
    "PRODUCT_DELETE": PRODUCT_DELETE_SYSTEM_PROMPT,
}
_TOOLS = {
    "PRODUCT_CREATE": "create_product_tool",
    "PRODUCT_UPDATE": "update_product_tool",
    "PRODUCT_DELETE": "delete_product_tool",
}
_CANCEL = re.compile(r"^\s*(cancel|stop|never ?mind|forget it|abort)\b", re.IGNORECASE)


@dataclass
class ProductManageTurn:
    answer: str
    pending_workflow: dict[str, Any] | None

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.pending_workflow and self.pending_workflow.get("waiting_for") == "confirmation")


class ProductManageState(MessagesState):
    system_prompt: str


def new_draft(intent: str) -> dict[str, Any]:
    return {"intent": intent, "draft": {}, "product_id": None, "current": None}


def _system_prompt(intent: str, pending: dict[str, Any]) -> str:
    base = _PROMPTS[intent]
    draft = dict(pending.get("draft") or {})
    if draft.get("image_url"):
        draft["image_url"] = f"{len(split_image_urls(draft['image_url']))} image(s) attached"
    compact: dict[str, Any] = {"draft": draft}
    if intent != "PRODUCT_CREATE":
        compact["product_id"] = pending.get("product_id")
        compact["product_name"] = (pending.get("current") or {}).get("name")
    return base + "\nCurrent draft: " + redact_sensitive_text(json.dumps(compact, ensure_ascii=False), max_length=2000)


def _build_graph(tools: list[Any], groq_client: Any):
    async def assistant(state: ProductManageState) -> dict[str, Any]:
        response = await groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=_to_groq_messages(state["messages"], state["system_prompt"]),
            tools=_tool_definitions(tools),
            tool_choice="auto",
            temperature=0,
        )
        choice = response.choices[0].message
        calls = []
        for call in choice.tool_calls or []:
            try:
                args = json.loads(call.function.arguments or "{}")
            except (TypeError, json.JSONDecodeError):
                args = {}
            calls.append({
                "name": call.function.name, "args": args if isinstance(args, dict) else {},
                "id": call.id, "type": "tool_call",
            })
        return {"messages": [AIMessage(content=choice.content or "", tool_calls=calls)]}

    def route_after_assistant(state: ProductManageState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    graph = StateGraph(ProductManageState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "assistant")
    graph.add_conditional_edges("assistant", route_after_assistant, {"tools": "tools", END: END})
    # The tool result already decides the reply, so one LLM call per turn is enough.
    graph.add_edge("tools", END)
    return graph.compile()


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def missing_fields_question(missing: list[str]) -> str:
    return "Got it. I still need: " + _join([FIELD_LABELS[name] for name in missing]) + "."


def _current_line(pending: dict[str, Any]) -> str:
    current = pending.get("current") or {}
    return (
        f"Current: price {_format_price(current.get('price'))}, stock {current.get('stock')}, "
        f"category {current.get('category') or 'unknown'}."
    )


def ready_for_confirmation(intent: str, pending: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    # A fresh id per summary makes buttons on an older summary stop working.
    confirmed = {**pending, "waiting_for": "confirmation", "confirm_id": secrets.token_hex(4)}
    return confirmation_summary(intent, confirmed), confirmed


def answer_for_state(intent: str, state: dict[str, Any], pending: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Turn a tool's outcome into the reply and the draft to keep."""
    status = state.get("status")
    pending = {**pending, "confirm_id": None}
    if status == "ready":
        return ready_for_confirmation(intent, pending)
    if status == "missing_fields":
        return missing_fields_question(state.get("missing") or []), {**pending, "waiting_for": "fields"}
    if status == "invalid":
        return " ".join(state.get("problems") or []), {**pending, "waiting_for": "fields"}
    if status == "category_not_found":
        message = category_not_found_message(state.get("category") or "", state.get("available") or [])
        return message, {**pending, "waiting_for": "fields"}
    if status == "choose_product":
        matches = state.get("matches") or []
        if not matches:
            return (
                f'I couldn\'t find a product named "{state.get("product_name")}" in your listings. '
                "Send the product ID or another name."
            ), {**pending, "waiting_for": "product"}
        lines = [f"#{m['id']} {m['name']} — {_format_price(m['price'])}" for m in matches]
        return "I found these products:\n" + "\n".join(lines) + "\nWhich one? Send its ID.", {
            **pending, "waiting_for": "product",
        }
    if status == "product_not_found":
        return (
            f"Product #{state.get('requested_id')} isn't in your listings. Send another product ID or name."
        ), {**pending, "waiting_for": "product"}
    if status == "need_product":
        verb = "delete" if intent == "PRODUCT_DELETE" else "change"
        return f"Which product do you want to {verb}? Send its ID or name.", {**pending, "waiting_for": "product"}
    if status == "need_changes":
        name = (pending.get("current") or {}).get("name")
        return (
            f"What would you like to change on #{pending.get('product_id')} ({name})? {_current_line(pending)}"
        ), {**pending, "waiting_for": "fields"}
    return state.get("error") or "Product changes are temporarily unavailable. Please try again later.", pending


async def run_product_manage_turn(
    text: str,
    access_token: str,
    role: str,
    intent: str,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    pending_workflow: dict[str, Any] | None = None,
    groq_client: Any | None = None,
) -> ProductManageTurn:
    """Run one turn of the create/update/delete conversation; credentials stay out of model state."""
    if intent not in PRODUCT_MANAGE_INTENTS:
        raise ValueError(f"Unsupported product intent: {intent}")
    pending = (
        pending_workflow
        if pending_workflow and pending_workflow.get("intent") == intent
        else new_draft(intent)
    )
    if pending_workflow and _CANCEL.match(text):
        logger.info("PRODUCT_DRAFT_CANCELLED=true")
        return ProductManageTurn("Okay, I cancelled that. Nothing was saved.", None)

    state: dict[str, Any] = {
        "draft": dict(pending.get("draft") or {}),
        "product_id": pending.get("product_id"),
        "current": pending.get("current"),
    }
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        tools = build_product_manage_tools(access_token, role, state)
        tools = [item for item in tools if item.name == _TOOLS[intent]]
        graph = _build_graph(tools, client)
        result = await graph.ainvoke(
            {
                "messages": _messages_from_history(recent_messages, text),
                "system_prompt": _system_prompt(intent, pending),
            },
            config={"recursion_limit": 6},
        )
    finally:
        if own_client:
            await client.close()

    updated = {
        **pending,
        "draft": state["draft"],
        "product_id": state.get("product_id"),
        "current": state.get("current"),
    }
    if state.get("status"):
        answer, updated = answer_for_state(intent, state, updated)
    elif pending.get("waiting_for") == "confirmation":
        # Only the Confirm button saves. A typed "yes" must not get a model
        # reply that sounds like the product was saved.
        summary, updated = ready_for_confirmation(intent, updated)
        answer = "Please use the buttons below.\n\n" + summary
    else:
        # No tool call: the model answered a side question; the draft stays open.
        answer = redact_sensitive_text(str(result["messages"][-1].content)).strip() or (
            "Tell me the product details, or say cancel to stop."
        )
        updated.setdefault("waiting_for", "fields")
    logger.info("PRODUCT_MANAGE_STATUS=%s waiting_for=%s", state.get("status") or "no_tool", updated.get("waiting_for"))
    return ProductManageTurn(answer, updated)
