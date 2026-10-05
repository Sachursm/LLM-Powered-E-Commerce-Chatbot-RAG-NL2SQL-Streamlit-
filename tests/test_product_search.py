"""Deterministic tests for category/product tools and the LangGraph loop."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-token")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from bot.agent.product_search import run_product_search, run_product_search_turn
from bot.agent.conversation import resolve_message_intent
from bot.tools.product_search import ProductSearchParams, build_product_search_tools, remove_category_terms

# These tests fake the category API, so keep a local Redis category cache out of them.
_cache_patches = (
    patch("bot.tools.product_search.get_cached_categories", AsyncMock(return_value=None)),
    patch("bot.tools.product_search.cache_categories", AsyncMock()),
)


def setUpModule():
    for item in _cache_patches:
        item.start()


def tearDownModule():
    for item in _cache_patches:
        item.stop()


def category_page(names: list[str]) -> dict:
    return {
        "status": 200,
        "data": {
            "items": [{"id": i + 1, "name": name} for i, name in enumerate(names)],
            "total": len(names), "skip": 0, "limit": 100, "has_more": False,
        },
    }


def product_page(
    items: list[dict], *, total: int | None = None, skip: int = 0,
    limit: int = 20, has_more: bool = False,
) -> dict:
    return {
        "status": 200,
        "data": {
            "items": items, "total": len(items) if total is None else total,
            "skip": skip, "limit": limit, "has_more": has_more,
        },
    }


def product_row(name: str, image_url: str = "") -> dict:
    return {
        "id": 1, "source_product_id": None, "name": name, "description": name,
        "price": 2499, "stock": 5, "image_url": image_url, "rating": 4.0,
        "ratings_count": 3, "category_id": 99, "seller_id": None,
    }


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_category_tool_matches_real_category_names(self):
        tools = build_product_search_tools("secret-jwt")
        category_tool = tools[0]
        api = AsyncMock(side_effect=[category_page(["Shoes", "Phones", "Laptops"])] * 3)
        with patch("bot.tools.product_search.api_get", api):
            self.assertEqual(json.loads(await category_tool.ainvoke({"product_phrase": "Nike shoes"}))["category"], "Shoes")
            self.assertEqual(json.loads(await category_tool.ainvoke({"product_phrase": "Samsung phones"}))["category"], "Phones")
            self.assertEqual(json.loads(await category_tool.ainvoke({"product_phrase": "running shoe"}))["category"], "Shoes")

    async def test_category_tool_matches_only_names_present_in_category_api(self):
        tools = build_product_search_tools("secret-jwt")
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=category_page(["Gaming Keyboard", "Shoes"]))):
            result = json.loads(await tools[0].ainvoke({"product_phrase": "keyboard"}))
        self.assertEqual(result["category"], "Gaming Keyboard")

    async def test_unknown_category_is_not_invented(self):
        tools = build_product_search_tools("secret-jwt")
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=category_page(["Shoes"]))):
            result = json.loads(await tools[0].ainvoke({"product_phrase": "Nike wearable device"}))
        self.assertIsNone(result["category"])
        self.assertEqual(result["available_categories"], ["Shoes"])

    async def test_category_api_failure_is_sanitized(self):
        tools = build_product_search_tools("secret-jwt")
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value={"status": 503, "data": {"detail": "internal"}})):
            result = json.loads(await tools[0].ainvoke({"product_phrase": "Nike shoes"}))
        self.assertIn("error", result)
        self.assertNotIn("internal", json.dumps(result))

    async def test_unmatched_category_returns_none_and_real_categories(self):
        tools = build_product_search_tools("secret-jwt")
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=category_page(["Shoes", "Electronics"]))):
            result = json.loads(await tools[0].ainvoke({"product_phrase": "gaming keyboard"}))
        self.assertIsNone(result["category"])
        self.assertEqual(result["available_categories"], ["Shoes", "Electronics"])

    async def test_product_query_maps_to_api_search_and_keeps_real_fields(self):
        tools = build_product_search_tools("secret-jwt")
        item = {
            "id": 12, "source_product_id": None, "name": "Nike Runner", "description": "A shoe",
            "price": 4200, "stock": 5, "image_url": "https://example.test/shoe.jpg",
            "rating": 4.5, "ratings_count": 10, "category_id": 1, "seller_id": 8,
        }
        api = AsyncMock(return_value=product_page([item]))
        with patch("bot.tools.product_search.api_get", api):
            result = json.loads(await tools[1].ainvoke({
                "query": "Nike", "category": "Shoes", "max_price": 5000,
            }))
        api.assert_awaited_once_with("/products/", token="secret-jwt", params={
            "skip": 0, "limit": 5, "search": "Nike", "category": "Shoes", "max_price": 5000.0,
        })
        self.assertEqual(result["items"][0]["name"], "Nike Runner")
        self.assertNotIn("source_product_id", result["items"][0])

    async def test_category_words_are_removed_from_query_seed(self):
        for seed, category, expected_search in (
            ("casual shoes", "casual-shoes", None),
            ("Nike shoes", "Shoes", "Nike"),
        ):
            with self.subTest(seed=seed):
                tools = build_product_search_tools("secret-jwt", query_seed=seed, force_query_seed=True)
                api = AsyncMock(return_value=product_page([]))
                with patch("bot.tools.product_search.api_get", api):
                    await tools[1].ainvoke({"category": category})
                self.assertEqual(api.await_args.kwargs["params"].get("search"), expected_search)
                self.assertEqual(api.await_args.kwargs["params"]["category"], category)

    async def test_found_category_replaces_search_and_is_used_when_model_omits_it(self):
        tools = build_product_search_tools("secret-jwt", query_seed="clothing", force_query_seed=True)
        api = AsyncMock(side_effect=[category_page(["Clothing", "Shoes"]), product_page([])])
        with patch("bot.tools.product_search.api_get", api):
            await tools[0].ainvoke({"product_phrase": "clothing"})
            await tools[1].ainvoke({"query": "clothing"})
        params = api.await_args.kwargs["params"]
        self.assertEqual(params["category"], "Clothing")
        self.assertNotIn("search", params)

    async def test_no_category_found_searches_query_only(self):
        tools = build_product_search_tools("secret-jwt", query_seed="gadget xyz", force_query_seed=True)
        api = AsyncMock(side_effect=[category_page(["Clothing", "Shoes"]), product_page([])])
        with patch("bot.tools.product_search.api_get", api):
            result = json.loads(await tools[0].ainvoke({"product_phrase": "gadget xyz"}))
            await tools[1].ainvoke({"query": "gadget xyz"})
        self.assertIsNone(result["category"])
        params = api.await_args.kwargs["params"]
        self.assertEqual(params["search"], "gadget xyz")
        self.assertNotIn("category", params)

    async def test_refinement_keeps_category_and_adds_words_to_search(self):
        tools = build_product_search_tools(
            "secret-jwt", query_seed="Nike shoes", default_filters={"category": "Shoes"},
        )
        api = AsyncMock(return_value=product_page([product_row("Nike Men Runner")]))
        with patch("bot.tools.product_search.api_get", api):
            await tools[1].ainvoke({"query": "men Nike shoes"})
        api.assert_awaited_once()
        params = api.await_args.kwargs["params"]
        self.assertEqual(params["category"], "Shoes")
        self.assertEqual(params["search"], "men Nike")

    def test_remove_category_terms(self):
        cases = (
            ("Nike shoes", "Shoes", "Nike"),
            ("running shoe", "Shoes", "running"),
            ("clothing", "Clothing", None),
            ("keyboard", "Gaming Keyboard", None),
            ("casual shoes for men", "Shoes", "casual men"),
            ("men's shoes", "Shoes", "men's"),
            ("Nike shoes", None, "Nike shoes"),
        )
        for query, category, expected in cases:
            with self.subTest(query=query, category=category):
                self.assertEqual(remove_category_terms(query, category), expected)

    async def test_continuation_defaults_preserve_context_filters(self):
        tools = build_product_search_tools(
            "secret-jwt", query_seed="casual shoes",
            default_filters={"category": "casual-shoes", "max_price": 3000},
        )
        api = AsyncMock(return_value=product_page([product_row("Men Casual Shoe")]))
        with patch("bot.tools.product_search.api_get", api):
            await tools[1].ainvoke({"query": "casual shoes for men"})
        api.assert_awaited_once()
        self.assertEqual(api.await_args.kwargs["params"]["search"], "men")
        self.assertEqual(api.await_args.kwargs["params"]["category"], "casual-shoes")
        self.assertEqual(api.await_args.kwargs["params"]["max_price"], 3000.0)
        self.assertNotIn("gender", api.await_args.kwargs["params"])

    async def test_unmatched_new_product_does_not_inherit_previous_category(self):
        tools = build_product_search_tools(
            "secret-jwt", query_seed="keyboard",
            default_filters={"category": "mobile-accessories"},
        )
        api = AsyncMock(side_effect=[
            category_page(["mobile-accessories", "Electronics"]),
            product_page([product_row("Mechanical Keyboard")]),
        ])
        with patch("bot.tools.product_search.api_get", api):
            await tools[0].ainvoke({"product_phrase": "keyboard"})
            result = json.loads(await tools[1].ainvoke({"query": "keyboard", "category": "mobile-accessories"}))
        params = api.await_args.kwargs["params"]
        self.assertNotIn("category", params)
        self.assertEqual(params["search"], "keyboard")
        self.assertIsNone(result["category"])

    async def test_empty_inherited_category_retries_without_category(self):
        tools = build_product_search_tools(
            "secret-jwt", query_seed="gaming keyboard",
            default_filters={"category": "mobile-accessories"},
        )
        api = AsyncMock(side_effect=[
            product_page([], total=0),
            product_page([product_row("Mechanical Keyboard")]),
        ])
        with patch("bot.tools.product_search.api_get", api):
            result = json.loads(await tools[1].ainvoke({"query": "gaming keyboard"}))
        first, retry = (call.kwargs["params"] for call in api.await_args_list)
        self.assertEqual(first["category"], "mobile-accessories")
        self.assertNotIn("category", retry)
        self.assertEqual(retry["search"], "gaming keyboard")
        self.assertEqual(result["items"][0]["name"], "Mechanical Keyboard")
        self.assertIsNone(result["category"])

    async def test_empty_category_found_this_turn_does_not_retry(self):
        tools = build_product_search_tools("secret-jwt", query_seed="red shoes")
        api = AsyncMock(side_effect=[category_page(["Shoes"]), product_page([], total=0)])
        with patch("bot.tools.product_search.api_get", api):
            await tools[0].ainvoke({"product_phrase": "red shoes"})
            result = json.loads(await tools[1].ainvoke({"query": "red shoes"}))
        self.assertEqual(api.await_count, 2)
        self.assertEqual(result["category"], "Shoes")

    async def test_no_products_returns_empty_page(self):
        tools = build_product_search_tools("secret-jwt")
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=product_page([], total=0))):
            result = json.loads(await tools[1].ainvoke({"max_price": 1000}))
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)

    async def test_fastapi_error_is_safe(self):
        tools = build_product_search_tools("secret-jwt")
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value={"status": 429, "data": {"detail": "private"}})):
            result = json.loads(await tools[1].ainvoke({}))
        self.assertIn("rate limited", result["error"])
        self.assertNotIn("private", json.dumps(result))

    def test_invalid_search_arguments_rejected(self):
        with self.assertRaises(ValueError):
            ProductSearchParams(min_price=500, max_price=100)
        with self.assertRaises(ValueError):
            ProductSearchParams(limit=101)
        with self.assertRaises(ValueError):
            ProductSearchParams(sort_by="newest")


class FakeGroqClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.replies)


def groq_reply(content=None, tool_calls=None):
    class Function:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class Call:
        def __init__(self, call_id, name, arguments):
            self.id = call_id
            self.function = Function(name, json.dumps(arguments))

    class Message:
        pass

    class Choice:
        pass

    class Response:
        pass

    message = Message()
    message.content = content
    message.tool_calls = [Call(*call) for call in (tool_calls or [])]
    choice = Choice()
    choice.message = message
    response = Response()
    response.choices = [choice]
    return response


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyboard_type_answer_reaches_main_llm_with_combined_context(self):
        pending = {
            "intent": "PRODUCT_SEARCH",
            "waiting_for": "product_type",
            "question": "What kind of keyboard are you looking for?",
            "context": {"query": "keyboard"},
        }
        history = [
            {"role": "user", "content": "do you have a keyboard"},
            {
                "role": "assistant",
                "content": "Sure! What kind of keyboard are you looking for? (e.g. mechanical, membrane, gaming, wireless, etc.)",
            },
            {"role": "user", "content": "gaming"},
        ]
        fake = FakeGroqClient([
            groq_reply(content="YES"),
            groq_reply(tool_calls=[("gaming-search", "product_search_tool", {"query": "gaming keyboard"})]),
            groq_reply(content="Here are gaming keyboards."),
        ])
        api = AsyncMock(return_value=product_page([], total=0))
        summary = "User is looking for a keyboard."
        with patch(
            "bot.agent.conversation.classify_intent",
            side_effect=AssertionError("YES must bypass Semantic Router"),
        ), patch(
            "bot.agent.conversation.resolve_fallback_intent",
            side_effect=AssertionError("YES must bypass intent fallback"),
        ):
            decision = await resolve_message_intent(
                "gaming", "USER", recent_messages=history,
                pending_workflow=pending,
                conversation_summary=summary,
                previous_user_message="do you have a keyboard",
                previous_bot_message=history[1]["content"],
                groq_client=fake,
            )
        self.assertTrue(decision["continuation"])

        detector_input = fake.requests[0]["messages"][1]["content"]
        self.assertIn("Previous user message: do you have a keyboard", detector_input)
        self.assertIn("Previous assistant response: Sure! What kind of keyboard are you looking for?", detector_input)
        self.assertIn("Current user message: gaming", detector_input)
        self.assertNotIn("Conversation summary:", detector_input)
        self.assertNotIn("Active context:", detector_input)
        with patch("bot.tools.product_search.api_get", api):
            turn = await run_product_search_turn(
                "gaming", "secret-jwt", recent_messages=history,
                pending_workflow=decision["continuation_context"],
                conversation_summary=summary,
                groq_client=fake,
            )

        model_input = json.dumps(fake.requests[1]["messages"])
        self.assertIn("User is looking for a keyboard.", model_input)
        self.assertIn("do you have a keyboard", model_input)
        self.assertIn("What kind of keyboard are you looking for?", model_input)
        self.assertIn("gaming", model_input)
        self.assertIn("waiting_for", model_input)
        self.assertEqual(api.await_args.kwargs["params"]["search"], "gaming keyboard")
        self.assertNotIn("secret-jwt", model_input)

    async def test_tool_loop_and_jwt_stays_out_of_groq_payload(self):
        token = "SENSITIVE_SENTINEL_JWT"
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("call-1", "category_tool", {"product_phrase": "Nike shoes"})]),
            groq_reply(tool_calls=[("call-2", "product_search_tool", {"query": "Nike", "category": "Shoes", "max_price": 5000})]),
            groq_reply(content="Nike Runner — ₹4,200."),
        ])
        rows = [{
            "id": 1, "source_product_id": None, "name": "Nike Runner", "description": "A shoe",
            "price": 4200, "stock": 5, "image_url": "", "rating": 4.5,
            "ratings_count": 10, "category_id": 1, "seller_id": None,
        }]
        api = AsyncMock(side_effect=[category_page(["Shoes"]), product_page(rows)])
        with patch("bot.tools.product_search.api_get", api):
            answer = await run_product_search("Show me Nike shoes under 5000", token, groq_client=fake)
        self.assertEqual(answer, "Nike Runner — ₹4,200.")
        self.assertEqual(api.await_count, 2)
        self.assertEqual(api.await_args_list[-1].kwargs["params"]["search"], "Nike")
        self.assertEqual(api.await_args_list[-1].kwargs["params"]["category"], "Shoes")
        self.assertNotIn(token, json.dumps(fake.requests))
        self.assertIn("openai/gpt-oss-20b", [request["model"] for request in fake.requests])

    async def test_successful_search_returns_active_context_for_future_refinements(self):
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("search-1", "product_search_tool", {"query": "casual", "category": "casual-shoes"})]),
            groq_reply(content="Here are the matching shoes."),
        ])
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=product_page([], total=0))):
            turn = await run_product_search_turn(
                "Do you have casual shoes?", "secret-jwt", groq_client=fake,
            )
        self.assertIsNone(turn.pending_workflow)
        self.assertEqual(turn.active_context["intent"], "PRODUCT_SEARCH")
        self.assertEqual(turn.active_context["context"]["query"], "casual shoes")
        self.assertEqual(turn.active_context["context"]["category"], "casual-shoes")

    async def test_stale_category_is_dropped_from_saved_context(self):
        active = {"intent": "PRODUCT_SEARCH", "context": {"query": "phone case", "category": "mobile-accessories"}}
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("s-1", "product_search_tool", {"query": "keyboard"})]),
            groq_reply(content="Here are some keyboards."),
        ])
        url = "http://img.test/1.jpg,http://img.test/2.jpg"
        api = AsyncMock(side_effect=[
            product_page([], total=0),
            product_page([product_row("Mechanical Keyboard", url)]),
        ])
        with patch("bot.tools.product_search.api_get", api):
            turn = await run_product_search_turn(
                "what about keyboard", "secret-jwt", active_context=active, groq_client=fake,
            )
        self.assertNotIn("category", turn.active_context["context"])
        self.assertEqual([p["name"] for p in turn.products], ["Mechanical Keyboard"])
        self.assertEqual(turn.products[0]["image_url"], "http://img.test/1.jpg")

    async def test_empty_model_reply_after_search_gets_fallback_text(self):
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("s-1", "product_search_tool", {"query": "keyboard"})]),
            groq_reply(content=""),
        ])
        api = AsyncMock(return_value=product_page([product_row("Mechanical Keyboard")]))
        with patch("bot.tools.product_search.api_get", api):
            turn = await run_product_search_turn("keyboard", "secret-jwt", groq_client=fake)
        self.assertEqual(turn.answer, "Here's what I found.")
        self.assertIsNone(turn.pending_workflow)

    async def test_more_request_after_last_page_says_no_more_without_searching(self):
        active = {
            "intent": "PRODUCT_SEARCH",
            "context": {"query": "bra", "category": "bra", "skip": 10, "limit": 5, "has_more": False, "total": 13},
        }
        fake = FakeGroqClient([])
        api = AsyncMock()
        with patch("bot.tools.product_search.api_get", api):
            turn = await run_product_search_turn(
                "is there any other bra", "secret-jwt", active_context=active, groq_client=fake,
            )
        self.assertEqual(turn.answer, "No more products found for bra. Would you like to try a different search?")
        self.assertEqual(turn.products, [])
        self.assertEqual(turn.active_context["context"]["skip"], 10)
        api.assert_not_awaited()
        self.assertEqual(fake.requests, [])

    def test_more_request_detection(self):
        from bot.agent.product_search import _is_more_request
        for text, expected in (
            ("is there any other bra", True),
            ("do you have more bras?", True),
            ("any others", True),
            ("anything else?", True),
            ("Show me more options", True),
            ("any other brand", False),
            ("do you have other colors", False),
            ("other shoes", False),
            ("bra", False),
        ):
            with self.subTest(text=text):
                self.assertEqual(_is_more_request(text, None, "bra"), expected)

    async def test_show_more_uses_authoritative_next_offset(self):
        active = {
            "intent": "PRODUCT_SEARCH",
            "context": {
                "query": "shoes", "category": "Shoes", "skip": 10,
                "limit": 10, "has_more": True,
            },
        }
        history = [
            {"role": "user", "content": "Do you have shoes?"},
            {"role": "assistant", "content": "I found shoes. Would you like to see more?"},
            {"role": "user", "content": "Yes"},
        ]
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("page-2", "product_search_tool", {"query": "shoes", "skip": 0, "limit": 20})]),
            groq_reply(content="Here are more shoes."),
        ])
        api = AsyncMock(return_value=product_page([], total=35, skip=20, limit=10, has_more=True))
        with patch("bot.tools.product_search.api_get", api):
            turn = await run_product_search_turn(
                "Yes", "secret-jwt", recent_messages=history,
                active_context=active, groq_client=fake,
            )
        self.assertEqual(api.await_args.kwargs["params"]["skip"], 20)
        self.assertEqual(api.await_args.kwargs["params"]["limit"], 10)
        self.assertEqual(turn.active_context["context"]["skip"], 20)
        self.assertTrue(turn.active_context["context"]["has_more"])

    async def test_followup_price_limit_replaces_previous_limit_in_context(self):
        from bot.agent.product_search import _initial_context

        existing = {"intent": "PRODUCT_SEARCH", "context": {"query": "shoes", "max_price": 1000}}
        context = _initial_context("Under 3000", None, existing)
        self.assertEqual(context["max_price"], 3000)

        pending = {
            "intent": "PRODUCT_SEARCH", "waiting_for": "product_type",
            "context": {"query": "shoes", "category": "Shoes", "max_price": 1000},
        }
        refined = _initial_context("casual", pending)
        self.assertEqual(refined["query"], "casual Shoes")
        self.assertEqual(refined["category"], "Shoes")
        self.assertEqual(refined["max_price"], 1000)

        no_category = {
            "intent": "PRODUCT_SEARCH", "waiting_for": "product_type",
            "context": {"query": "keyboard"},
        }
        clarified = _initial_context("gaming keyboard", no_category)
        self.assertEqual(clarified["query"], "gaming keyboard")
        self.assertIsNone(clarified.get("category"))

    async def test_product_api_failure_never_puts_jwt_in_result(self):
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("call-1", "product_search_tool", {})]),
            groq_reply(content="Search is temporarily unavailable."),
        ])
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value={"status": 503, "data": {"detail": "private"}})):
            answer = await run_product_search("Find products", "SENSITIVE_SENTINEL_JWT", groq_client=fake)
        self.assertNotIn("SENSITIVE_SENTINEL_JWT", answer)
        self.assertNotIn("SENSITIVE_SENTINEL_JWT", json.dumps(fake.requests))

    async def test_clarification_state_continues_and_empty_results_stay_honest(self):
        token = "SENSITIVE_SENTINEL_JWT"
        clarify_llm = FakeGroqClient([
            groq_reply(tool_calls=[("category-1", "category_tool", {"product_phrase": "shoes"})]),
            groq_reply(content="What type of shoes would you like?"),
        ])
        with patch(
            "bot.tools.product_search.api_get",
            AsyncMock(return_value=category_page(["Shoes"])),
        ):
            first = await run_product_search_turn(
                "Do you have shoes under 1000 rupees?",
                token,
                groq_client=clarify_llm,
            )
        self.assertEqual(first.pending_workflow["waiting_for"], "product_type")
        self.assertEqual(first.pending_workflow["context"]["category"], "Shoes")
        self.assertEqual(first.pending_workflow["context"]["max_price"], 1000)

        history = [
            {"role": "user", "content": "Do you have shoes under 1000 rupees?"},
            {"role": "assistant", "content": first.answer},
            {"role": "user", "content": "casual"},
        ]
        followup_llm = FakeGroqClient([
            groq_reply(tool_calls=[(
                "products-1", "product_search_tool",
                {"query": "casual", "category": "Shoes", "max_price": 1000},
            )]),
            groq_reply(content="I couldn't find any casual shoes under ₹1,000."),
        ])
        api = AsyncMock(return_value=product_page([], total=0))
        with patch("bot.tools.product_search.api_get", api):
            followup = await run_product_search_turn(
                "casual",
                token,
                recent_messages=history,
                pending_workflow=first.pending_workflow,
                groq_client=followup_llm,
            )
        self.assertIsNone(followup.pending_workflow)
        self.assertEqual(followup.products_returned, 0)
        self.assertIn("couldn't find", followup.answer)
        self.assertIn("What type of shoes", json.dumps(followup_llm.requests))
        followup_payload = json.dumps(followup_llm.requests)
        self.assertIn("max_price", followup_payload)
        self.assertIn("1000", followup_payload)
        self.assertNotIn(token, json.dumps(followup_llm.requests))

    async def test_unmatched_category_asks_for_clarification(self):
        token = "SENSITIVE_SENTINEL_JWT"
        first_llm = FakeGroqClient([
            groq_reply(tool_calls=[("category-1", "category_tool", {"product_phrase": "keyboard"})]),
            groq_reply(content="What kind of keyboard are you looking for, such as gaming or mechanical?"),
        ])
        with patch(
            "bot.tools.product_search.api_get",
            AsyncMock(return_value=category_page(["Shoes", "Phones"])),
        ):
            first = await run_product_search_turn(
                "Do you have a keyboard?", token, groq_client=first_llm,
            )
        self.assertEqual(first.pending_workflow["waiting_for"], "product_type")
        self.assertIsNone(first.active_context["context"].get("category"))

    async def test_clarified_product_search_uses_query_without_missing_category(self):
        token = "SENSITIVE_SENTINEL_JWT"
        pending = {
            "intent": "PRODUCT_SEARCH", "waiting_for": "product_type",
            "initial_query": "Do you have a keyboard?",
            "context": {"query": "keyboard"},
        }
        history = [
            {"role": "user", "content": "Do you have a keyboard?"},
            {"role": "assistant", "content": "What kind of keyboard?"},
            {"role": "user", "content": "gaming keyboard"},
        ]
        second_llm = FakeGroqClient([
            groq_reply(tool_calls=[("products-1", "product_search_tool", {"query": "gaming keyboard", "category": None})]),
            groq_reply(content="I couldn't find any matching gaming keyboards."),
        ])
        api = AsyncMock(return_value=product_page([], total=0))
        with patch("bot.tools.product_search.api_get", api):
            second = await run_product_search_turn(
                "gaming keyboard", token, recent_messages=history,
                pending_workflow=pending, groq_client=second_llm,
            )
        self.assertIsNone(second.pending_workflow)
        self.assertEqual(api.await_args.kwargs["params"]["search"], "gaming keyboard")
        self.assertNotIn("category", api.await_args.kwargs["params"])
        self.assertEqual(second.products_returned, 0)
        self.assertIn("couldn't find", second.answer)
        self.assertNotIn(token, json.dumps(second_llm.requests))

if __name__ == "__main__":
    unittest.main()
