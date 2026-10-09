"""Category view (no LLM) and the LangGraph create/update/delete draft workflow."""

import json
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from groq import AsyncGroq

from bot.agent.product_manage import _CANCEL, _build_graph
from bot.agent.product_search import _messages_from_history
from bot.config import settings
from bot.prompts.category_manage import (
    CATEGORY_CREATE_SYSTEM_PROMPT,
    CATEGORY_DELETE_SYSTEM_PROMPT,
    CATEGORY_UPDATE_SYSTEM_PROMPT,
)
from bot.services.category_match import closest_categories, find_exact
from bot.services.safety import redact_sensitive_text
from bot.tools.category_manage import (
    CATEGORY_MANAGE_INTENTS,
    build_category_manage_tools,
    category_ref,
    choose_category,
    confirmation_summary,
    extract_category_phrase,
)
from bot.tools.product_search import _get_categories

logger = logging.getLogger(__name__)

_PROMPTS = {
    "CATEGORY_CREATE": CATEGORY_CREATE_SYSTEM_PROMPT,
    "CATEGORY_UPDATE": CATEGORY_UPDATE_SYSTEM_PROMPT,
    "CATEGORY_DELETE": CATEGORY_DELETE_SYSTEM_PROMPT,
}
_TOOLS = {
    "CATEGORY_CREATE": "create_category_tool",
    "CATEGORY_UPDATE": "update_category_tool",
    "CATEGORY_DELETE": "delete_category_tool",
}


@dataclass
class CategoryTurn:
    """One reply. ``choices`` become category buttons; ``page_from`` adds a full paged list."""

    answer: str
    pending_workflow: dict[str, Any] | None
    choices: list[dict[str, Any]] = field(default_factory=list)
    page_from: int | None = None

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.pending_workflow and self.pending_workflow.get("waiting_for") == "confirmation")


# ---------------------------------------------------------------- view

async def run_category_view_turn(text: str, access_token: str) -> CategoryTurn:
    """Answer "what categories do you have" / "categories like footwear" with buttons."""
    categories = await _get_categories(access_token)
    waiting = {"intent": "CATEGORY", "waiting_for": "category"}
    if not categories:
        return CategoryTurn("There are no categories yet.", None)
    phrase = extract_category_phrase(text)
    logger.info("CATEGORY_VIEW phrase=%s", phrase or "<none>")
    if not phrase:
        return CategoryTurn(
            f"Which category are you looking for? Type a name, or pick one of our {len(categories)} categories below.",
            waiting, page_from=0,
        )
    exact = find_exact(phrase, categories)
    if exact is not None:
        return CategoryTurn(f'Yes, we have "{exact.name}". Tap it to see its products.', None, [category_ref(exact)])
    close = await closest_categories(phrase, categories)
    if close:
        return CategoryTurn(
            f'We don\'t have a "{phrase}" category. These are the closest:',
            waiting, [category_ref(c) for c, _ in close],
        )
    return CategoryTurn(
        f'I couldn\'t find a category like "{phrase}". Here are all our categories:', waiting, page_from=0,
    )


# ---------------------------------------------------------------- create/update/delete

def new_draft(intent: str) -> dict[str, Any]:
    return {"intent": intent, "draft": {}}


def _system_prompt(intent: str, pending: dict[str, Any]) -> str:
    draft = {k: v for k, v in (pending.get("draft") or {}).items() if k != "similar"}
    compact = {"draft": draft, "waiting_for": pending.get("waiting_for")}
    return _PROMPTS[intent] + "\nCurrent draft: " + redact_sensitive_text(json.dumps(compact, ensure_ascii=False), max_length=1000)


def ready_for_confirmation(intent: str, pending: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    # A fresh id per summary makes buttons on an older summary stop working.
    confirmed = {**pending, "waiting_for": "confirmation", "confirm_id": secrets.token_hex(4)}
    return confirmation_summary(intent, confirmed), confirmed


def answer_for_state(intent: str, state: dict[str, Any], pending: dict[str, Any]) -> CategoryTurn:
    """Turn a tool's outcome into the reply, any buttons, and the draft to keep."""
    status = state.get("status")
    pending = {**pending, "confirm_id": None}
    name = ((pending.get("draft") or {}).get("category") or {}).get("name")
    if status == "ready":
        answer, confirmed = ready_for_confirmation(intent, pending)
        return CategoryTurn(answer, confirmed)
    if status == "need_name":
        return CategoryTurn("What should the new category be called?", {**pending, "waiting_for": "name"})
    if status == "exists":
        return CategoryTurn(f'Category "{state.get("existing")}" already exists.', None)
    if status == "need_category":
        verb = "rename" if intent == "CATEGORY_UPDATE" else "delete"
        return CategoryTurn(
            f"Which category do you want to {verb}? Type its name, or pick one below.",
            {**pending, "waiting_for": "category"}, page_from=0,
        )
    if status == "category_not_found":
        suggestions = state.get("suggestions") or []
        requested = state.get("requested")
        if suggestions:
            return CategoryTurn(
                f'Category "{requested}" not found. Did you mean one of these?',
                {**pending, "waiting_for": "category"}, suggestions,
            )
        return CategoryTurn(
            f'Category "{requested}" not found, and none are close. Pick one below or type another name.',
            {**pending, "waiting_for": "category"}, page_from=0,
        )
    if status == "need_new_name":
        return CategoryTurn(f'What should "{name}" be renamed to?', {**pending, "waiting_for": "new_name"})
    if status == "same_name":
        return CategoryTurn(f'"{name}" already has that name. What should it be renamed to?', {
            **pending, "waiting_for": "new_name",
        })
    if status == "name_taken":
        return CategoryTurn(f'A category named "{state.get("taken")}" already exists. Pick another name.', {
            **pending, "waiting_for": "new_name",
        })
    if status == "in_use":
        count = state.get("count")
        noun = "product uses" if count == 1 else "products use"
        return CategoryTurn(
            f'Can\'t delete "{name}" because {count} {noun} it. Move them to another category first.', None,
        )
    if status == "invalid":
        return CategoryTurn(state.get("problem") or "That name isn't valid.", {**pending, "waiting_for": pending.get("waiting_for") or "name"})
    return CategoryTurn(state.get("error") or "Category changes are temporarily unavailable. Please try again later.", pending)


async def apply_category_pick(access_token: str, pending: dict[str, Any], category_id: int) -> CategoryTurn:
    """Handle a tapped suggestion button for a rename/delete draft (no LLM call)."""
    intent = pending["intent"]
    categories = await _get_categories(access_token)
    category = next((c for c in categories if c.id == category_id), None)
    if category is None:
        return CategoryTurn("That category no longer exists. Type another name.", {**pending, "waiting_for": "category"})
    state: dict[str, Any] = {"intent": intent, "draft": dict(pending.get("draft") or {})}
    await choose_category(access_token, state, category)
    return answer_for_state(intent, state, {**pending, "draft": state["draft"]})


async def run_category_manage_turn(
    text: str,
    access_token: str,
    intent: str,
    *,
    recent_messages: list[dict[str, str]] | None = None,
    pending_workflow: dict[str, Any] | None = None,
    groq_client: Any | None = None,
) -> CategoryTurn:
    """Run one turn of the create/rename/delete conversation."""
    if intent not in CATEGORY_MANAGE_INTENTS:
        raise ValueError(f"Unsupported category intent: {intent}")
    pending = (
        pending_workflow
        if pending_workflow and pending_workflow.get("intent") == intent
        else new_draft(intent)
    )
    if pending_workflow and _CANCEL.match(text):
        logger.info("CATEGORY_DRAFT_CANCELLED=true")
        return CategoryTurn("Okay, I cancelled that. Nothing was changed.", None)

    state: dict[str, Any] = {"intent": intent, "draft": dict(pending.get("draft") or {})}
    own_client = groq_client is None
    client = groq_client or AsyncGroq(api_key=settings.GROQ_API_KEY)
    try:
        tools = [t for t in build_category_manage_tools(access_token, state) if t.name == _TOOLS[intent]]
        result = await _build_graph(tools, client).ainvoke(
            {
                "messages": _messages_from_history(recent_messages, text),
                "system_prompt": _system_prompt(intent, pending),
            },
            config={"recursion_limit": 6},
        )
    finally:
        if own_client:
            await client.close()

    updated = {**pending, "draft": state["draft"]}
    if state.get("status"):
        turn = answer_for_state(intent, state, updated)
    elif pending.get("waiting_for") == "confirmation":
        # Only the Confirm button changes anything; see run_product_manage_turn.
        answer, confirmed = ready_for_confirmation(intent, updated)
        turn = CategoryTurn("Please use the buttons below.\n\n" + answer, confirmed)
    else:
        answer = redact_sensitive_text(str(result["messages"][-1].content)).strip()
        turn = CategoryTurn(answer or "Tell me the category name, or say cancel to stop.", {
            **updated, "waiting_for": updated.get("waiting_for") or "name",
        })
    logger.info("CATEGORY_MANAGE_STATUS=%s waiting_for=%s", state.get("status") or "no_tool",
                (turn.pending_workflow or {}).get("waiting_for"))
    return turn
