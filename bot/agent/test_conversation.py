"""Role filtering, fallback routing, and pending-turn memory tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.agent.conversation import resolve_message_intent
from bot.router.semantic import classify_intent
from bot.services.session import (
    append_recent_message,
    save_conversation_memory,
    summarize_conversation,
    summarize_pending_workflow,
)


class FakeSemanticRouter:
    def __init__(self):
        self.last_candidates = None
        self.last_text = None

    def __call__(self, *, text, route_filter, limit):
        self.last_text = text
        self.last_candidates = set(route_filter)
        route = "PRODUCT_SEARCH" if "PRODUCT_SEARCH" in self.last_candidates else sorted(self.last_candidates)[0]
        if text.casefold().strip() == "show my products" and "SELLER_PRODUCT" in self.last_candidates:
            route = "SELLER_PRODUCT"
        return SimpleNamespace(name=route, similarity_score=0.82)


class FakeFallbackClient:
    def __init__(self, decision):
        self.decision = decision
        self.chat = self
        self.completions = self
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.decision))])


class RoleCandidateTests(unittest.TestCase):
    def test_user_never_has_seller_product_as_candidate(self):
        fake = FakeSemanticRouter()
        with patch("bot.router.semantic._get_router", return_value=fake):
            result = classify_intent("What are the product you have", "USER")
        self.assertEqual(result["intent"], "PRODUCT_SEARCH")
        self.assertNotIn("SELLER_PRODUCT", fake.last_candidates)

    def test_required_role_aware_catalog_phrases(self):
        fake = FakeSemanticRouter()
        with patch("bot.router.semantic._get_router", return_value=fake):
            user_products = classify_intent("show products", "USER")
            seller_products = classify_intent("show my products", "SELLER")
            seller_browse = classify_intent("browse products", "SELLER")
        self.assertEqual(user_products["intent"], "PRODUCT_SEARCH")
        self.assertEqual(seller_products["intent"], "SELLER_PRODUCT")
        self.assertEqual(seller_browse["intent"], "PRODUCT_SEARCH")

    def test_user_possessive_inventory_language_is_not_seller_route(self):
        with patch("bot.router.semantic._get_router", return_value=FakeSemanticRouter()):
            self.assertEqual(
                classify_intent("what products do I have", "USER")["intent"],
                "PRODUCT_SEARCH",
            )

    def test_sensitive_token_is_redacted_before_semantic_router_input(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturevalue"
        fake = FakeSemanticRouter()
        with patch("bot.router.semantic._get_router", return_value=fake):
            classify_intent(token, "USER")
        self.assertNotIn(token, fake.last_text)
        self.assertIn("REDACTED", fake.last_text)


class ConversationRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_previous_exchange_skips_detector_even_with_stale_workflow_context(self):
        fake = FakeFallbackClient("YES")
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "GENERAL_CHAT", "confidence": 0.9},
        ) as router:
            result = await resolve_message_intent(
                "hi", "USER",
                active_context={"intent": "PRODUCT_SEARCH", "context": {"query": "keyboard"}},
                groq_client=fake,
            )

        self.assertEqual(result["intent"], "GENERAL_CHAT")
        self.assertFalse(result["continuation"])
        self.assertEqual(fake.requests, [])
        router.assert_called_once_with("hi", "USER")

    async def test_exact_three_message_exchange_routes_new_request_then_bypasses_router(self):
        greeting = "Hi! I can help you search SachuMart products. What are you looking for?"
        clarification = (
            "What kind of keyboard are you looking for? "
            "(e.g., mechanical, membrane, gaming, etc.)"
        )
        history: list[dict[str, str]] = []
        first_detector_client = FakeFallbackClient("YES")
        no_client = FakeFallbackClient("NO")

        # Message 1 has no prior exchange, so only the router runs.
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "GENERAL_CHAT", "confidence": 0.9},
        ) as router:
            first = await resolve_message_intent(
                "hi", "USER", recent_messages=append_recent_message(history, "user", "hi"),
                groq_client=first_detector_client,
            )
        self.assertEqual(first["intent"], "GENERAL_CHAT")
        self.assertFalse(first_detector_client.requests)
        router.assert_called_once_with("hi", "USER")
        history = append_recent_message(history, "user", "hi")
        history = append_recent_message(history, "assistant", greeting)

        # Message 2 is unrelated to the greeting: detector says NO, then the
        # router sees only the current message. Detection uses the old exchange
        # even though the current user message is present in the local window.
        current_search = "i am looking for a keyboard"
        current_window = append_recent_message(history, "user", current_search)
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "PRODUCT_SEARCH", "confidence": 0.9},
        ) as router:
            second = await resolve_message_intent(
                current_search, "USER", recent_messages=current_window,
                groq_client=no_client,
            )
        self.assertEqual(second["intent"], "PRODUCT_SEARCH")
        self.assertFalse(second["continuation"])
        router.assert_called_once_with(current_search, "USER")
        detector_prompt = no_client.requests[0]["messages"][1]["content"]
        self.assertIn("Previous user message: hi", detector_prompt)
        self.assertIn(f"Previous assistant response: {greeting}", detector_prompt)
        self.assertIn(f"Current user message: {current_search}", detector_prompt)
        history = current_window
        history = append_recent_message(history, "assistant", clarification)

        # Message 3 answers the clarification. The old previous exchange is
        # read before any state update, and YES bypasses router and fallback.
        yes_client = FakeFallbackClient("YES")
        current_window = append_recent_message(history, "user", "gaming")
        pending = {
            "intent": "PRODUCT_SEARCH", "waiting_for": "product_type",
            "question": clarification, "context": {"query": "keyboard"},
        }
        with patch(
            "bot.agent.conversation.classify_intent",
            side_effect=AssertionError("YES must bypass Semantic Router"),
        ) as router, patch(
            "bot.agent.conversation.resolve_fallback_intent",
            side_effect=AssertionError("YES must bypass intent fallback"),
        ):
            third = await resolve_message_intent(
                "gaming", "USER", recent_messages=current_window,
                pending_workflow=pending,
                conversation_summary="User is looking for a keyboard.",
                groq_client=yes_client,
            )
        self.assertEqual(third["intent"], "PRODUCT_SEARCH")
        self.assertTrue(third["continuation"])
        router.assert_not_called()
        detector_prompt = yes_client.requests[0]["messages"][1]["content"]
        self.assertIn(f"Previous user message: {current_search}", detector_prompt)
        self.assertIn(f"Previous assistant response: {clarification}", detector_prompt)
        self.assertIn("Current user message: gaming", detector_prompt)

    async def test_keyboard_query_can_take_llm_product_search_fallback(self):
        fake = FakeFallbackClient("PRODUCT_SEARCH")
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "UNKNOWN", "confidence": 0.29, "query": "have you got keyboards"},
        ):
            result = await resolve_message_intent(
                "have you got keyboards", "USER", groq_client=fake
            )
        self.assertEqual(result["intent"], "PRODUCT_SEARCH")
        self.assertTrue(result["fallback_used"])
        self.assertIn("PRODUCT_SEARCH", fake.requests[0]["messages"][1]["content"])

    async def test_actual_keyboard_and_generic_inventory_queries_reach_product_search(self):
        fake = FakeFallbackClient("PRODUCT_SEARCH")
        for query, initial_intent in (("do you have keyboard", "UNKNOWN"), ("What are the product you have", "PRODUCT_SEARCH")):
            with self.subTest(query=query), patch(
                "bot.agent.conversation.classify_intent",
                return_value={"intent": initial_intent, "confidence": 0.29},
            ):
                result = await resolve_message_intent(query, "USER", groq_client=fake)
                self.assertEqual(result["intent"], "PRODUCT_SEARCH")

    async def test_sensitive_token_is_redacted_from_fallback_prompt(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturevalue"
        fake = FakeFallbackClient("GENERAL_CHAT")
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "UNKNOWN", "confidence": 0.1, "query": token},
        ):
            await resolve_message_intent(token, "USER", groq_client=fake)
        self.assertNotIn(token, str(fake.requests))

    async def test_any_kind_and_casual_continue_pending_search(self):
        pending = {
            "intent": "PRODUCT_SEARCH",
            "context": {"category": "Shoes", "max_price": 1000},
            "waiting_for": "product_type",
            "question": "What type of shoes?",
        }
        with patch(
            "bot.agent.conversation.classify_intent",
            side_effect=AssertionError("pending continuation should not route independently"),
        ):
            for reply in ("any kind", "casual"):
                with self.subTest(reply=reply):
                    result = await resolve_message_intent(
                        reply, "USER", pending_workflow=pending,
                        previous_user_message="Do you have shoes?",
                        previous_bot_message="What type of shoes are you looking for?",
                        groq_client=FakeFallbackClient("YES"),
                    )
                    self.assertEqual(result["intent"], "PRODUCT_SEARCH")
                    self.assertTrue(result["continuation"])
                    self.assertFalse(result["fallback_used"])

    async def test_new_order_request_can_exit_pending_product_clarification(self):
        pending = {
            "intent": "PRODUCT_SEARCH", "waiting_for": "product_type",
            "context": {"query": "keyboard"},
        }
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "ORDER_STATUS", "confidence": 0.9},
        ):
            result = await resolve_message_intent(
                "Where is my order?", "USER", pending_workflow=pending,
                groq_client=FakeFallbackClient("NO"),
            )
        self.assertEqual(result["intent"], "ORDER_STATUS")
        self.assertFalse(result["continuation"])

    async def test_active_search_followups_continue_without_independent_semantic_route(self):
        active = {
            "intent": "PRODUCT_SEARCH",
            "context": {"query": "casual shoes", "category": "casual-shoes", "max_price": 1000},
        }
        for reply in ("For men", "Any kind", "Under 3000", "What about Adidas?", "Show me more options"):
            with self.subTest(reply=reply), patch(
                "bot.agent.conversation.classify_intent",
                side_effect=AssertionError("continuation must not route independently"),
            ):
                result = await resolve_message_intent(
                    reply, "USER", active_context=active,
                    previous_user_message="Do you have casual shoes?",
                    previous_bot_message="I found some casual shoes.",
                    groq_client=FakeFallbackClient("YES"),
                )
                self.assertEqual(result["intent"], "PRODUCT_SEARCH")
                self.assertTrue(result["continuation"])

    async def test_active_search_can_be_replaced_by_order_status_request(self):
        active = {"intent": "PRODUCT_SEARCH", "context": {"query": "casual shoes"}}
        fake = FakeFallbackClient("NO")
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "ORDER_STATUS", "confidence": 0.9},
        ) as classifier:
            result = await resolve_message_intent(
                "Where is my order?", "USER", active_context=active,
                conversation_summary="User is looking for shoes.",
                previous_user_message="do you have shoes",
                previous_bot_message="I found some shoes.",
                groq_client=fake,
            )
        self.assertEqual(result["intent"], "ORDER_STATUS")
        self.assertFalse(result["continuation"])
        classifier.assert_called_once_with("Where is my order?", "USER")

    async def test_active_context_decision_never_receives_session_jwt(self):
        token = "SENSITIVE_SENTINEL_JWT"
        fake = FakeFallbackClient("YES")
        await resolve_message_intent(
            "For men", "USER",
            active_context={"intent": "PRODUCT_SEARCH", "context": {"query": "shoes"}},
            recent_messages=[
                {"role": "user", "content": "shoes"},
                {"role": "assistant", "content": "I found shoes."},
            ],
            groq_client=fake,
        )
        self.assertNotIn(token, str(fake.requests))

    async def test_continuation_output_must_be_exact_yes_or_no(self):
        from bot.agent.intent_fallback import detect_continuation

        for output in ("", "YES, it continues", "CONTINUE", "NO because unrelated", "maybe"):
            with self.subTest(output=output):
                fake = FakeFallbackClient(output)
                result = await detect_continuation(
                    "For men", "Do you have casual shoes?", "I found matching shoes",
                    groq_client=fake,
                )
                self.assertEqual(result, "NO")
                self.assertGreaterEqual(fake.requests[0]["max_tokens"], 64)

        fake = FakeFallbackClient("YES")
        result = await detect_continuation(
            "For men", "Do you have casual shoes?", "I found shoes",
            groq_client=fake,
        )
        self.assertEqual(result, "YES")
        detector_prompt = fake.requests[0]["messages"][1]["content"]
        for field in ("Previous user message: Do you have casual shoes?", "Previous assistant response: I found shoes", "Current user message: For men"):
            self.assertIn(field, detector_prompt)
        self.assertNotIn("Conversation summary:", detector_prompt)
        self.assertNotIn("Active context:", detector_prompt)

    async def test_detector_is_told_the_current_task(self):
        from bot.agent.intent_fallback import detect_continuation

        fake = FakeFallbackClient("NO")
        await detect_continuation(
            "delete category test1", "show me shoes", "Here are some shoes.",
            current_task="PRODUCT_SEARCH", groq_client=fake,
        )
        detector_prompt = fake.requests[0]["messages"][1]["content"]
        self.assertIn("The current action is: search or browse products", detector_prompt)
        # Every action is listed, with look-alike commands for other actions.
        self.assertIn("- delete a product category", detector_prompt)
        self.assertIn("- delete a product listing", detector_prompt)
        self.assertIn("'remove test1 from categories' (delete a category)", detector_prompt)
        self.assertIn("'remove Nike' (drops a filter)", detector_prompt)

    async def test_command_for_another_task_goes_to_the_router(self):
        active = {"intent": "PRODUCT_SEARCH", "context": {"query": "shoes"}}
        fake = FakeFallbackClient("NO")
        with patch(
            "bot.agent.conversation.classify_intent",
            return_value={"intent": "CATEGORY_DELETE", "confidence": 1.0, "query": "delete category test1"},
        ) as router:
            decision = await resolve_message_intent(
                "delete category test1", "ADMIN", active_context=active,
                previous_user_message="show me shoes", previous_bot_message="Here are some shoes.",
                groq_client=fake,
            )
        router.assert_called_once()
        self.assertEqual(decision["intent"], "CATEGORY_DELETE")
        self.assertFalse(decision["continuation"])
        self.assertIn("The current action is: search or browse products", fake.requests[0]["messages"][1]["content"])

    async def test_gaming_continues_pending_keyboard_clarification(self):
        pending = {
            "intent": "PRODUCT_SEARCH", "waiting_for": "product_type",
            "question": "What type of keyboard?", "context": {"query": "keyboard"},
        }
        fake = FakeFallbackClient("YES")
        with patch(
            "bot.agent.conversation.classify_intent",
            side_effect=AssertionError("clarification reply bypasses semantic router"),
        ):
            result = await resolve_message_intent(
                "Gaming", "USER", pending_workflow=pending,
                conversation_summary="User is looking for a keyboard.",
                recent_messages=[
                    {"role": "user", "content": "What keyboard do you have?"},
                    {"role": "assistant", "content": "What type of keyboard?"},
                    {"role": "user", "content": "Gaming"},
                ],
                groq_client=fake,
            )
        self.assertTrue(result["continuation"])
        detector_prompt = fake.requests[0]["messages"][1]["content"]
        self.assertIn("Previous user message: What keyboard do you have?", detector_prompt)
        self.assertIn("Previous assistant response: What type of keyboard?", detector_prompt)
        self.assertIn("Current user message: Gaming", detector_prompt)
        self.assertNotIn("Conversation summary:", detector_prompt)

    async def test_yes_after_more_prompt_continues(self):
        active = {"intent": "PRODUCT_SEARCH", "context": {"query": "shoes", "has_more": True}}
        with patch(
            "bot.agent.conversation.classify_intent",
            side_effect=AssertionError("router should be skipped"),
        ):
            result = await resolve_message_intent(
                "Yes", "USER", active_context=active,
                previous_user_message="Do you have shoes?",
                previous_bot_message="Would you like to see more?",
                groq_client=FakeFallbackClient("YES"),
            )
        self.assertTrue(result["continuation"])

    def test_memory_is_bounded_and_summary_keeps_active_filters(self):
        messages = []
        for index in range(10):
            messages = append_recent_message(messages, "user", f"message {index}")
        self.assertEqual(len(messages), 8)
        self.assertEqual(messages[0]["content"], "message 2")
        summary = summarize_pending_workflow({
            "intent": "PRODUCT_SEARCH",
            "context": {"category": "Shoes", "max_price": 1000},
            "waiting_for": "product_type",
        })
        self.assertIn("category=Shoes", summary)
        self.assertIn("max_price=1000", summary)
        self.assertIn("waiting_for=product_type", summary)

        active_summary = summarize_pending_workflow(None, {
            "intent": "PRODUCT_SEARCH",
            "context": {"query": "casual shoes", "category": "casual-shoes", "max_price": 1000},
        })
        self.assertIn("query=casual shoes", active_summary)
        self.assertIn("category=casual-shoes", active_summary)

    async def test_memory_and_pending_workflow_are_saved_in_existing_session(self):
        session = {"token": "server-side-only", "role": "USER", "state": "LOGGED_IN"}
        pending = {
            "intent": "PRODUCT_SEARCH",
            "context": {"category": "Shoes", "max_price": 1000},
            "waiting_for": "product_type",
        }
        with patch("bot.services.session.get_session", return_value=session) as get_saved, patch(
            "bot.services.session.set_session"
        ) as set_saved:
            set_saved.return_value = None
            await save_conversation_memory(
                42,
                recent_messages=[{"role": "user", "content": "casual"}],
                pending_workflow=pending,
                active_context={"intent": "PRODUCT_SEARCH", "context": pending["context"]},
            )
        get_saved.assert_awaited_once_with(42)
        set_saved.assert_awaited_once()
        persisted = set_saved.await_args.args[1]
        self.assertEqual(persisted["pending_workflow"], pending)
        self.assertEqual(persisted["active_context"]["intent"], "PRODUCT_SEARCH")
        self.assertEqual(persisted["conversation"]["recent_messages"][0]["content"], "casual")
        self.assertIn("casual", persisted["conversation"]["summary"])
        self.assertEqual(persisted["conversation"]["previous_user_message"], "casual")

    def test_conversation_memory_redacts_jwt_from_summary_and_recent_messages(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturevalue"
        message = append_recent_message([], "user", f"Search for shoes {token}")
        self.assertNotIn(token, message[0]["content"])
        summary = summarize_conversation(message)
        self.assertNotIn(token, summary)


class RedisSessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_expiry_is_set_to_thirty_minutes(self):
        from bot.services.session import SESSION_TTL_SECONDS, set_session

        with patch("bot.services.session._redis.set", new_callable=AsyncMock) as redis_set:
            await set_session(7, {"state": "LOGGED_IN", "active_context": {"intent": "PRODUCT_SEARCH"}})
        self.assertEqual(redis_set.await_args.kwargs["ex"], SESSION_TTL_SECONDS)
        self.assertEqual(SESSION_TTL_SECONDS, 1800)

    async def test_logout_session_delete_removes_all_conversation_data(self):
        from bot.services.session import delete_session

        with patch("bot.services.session._redis.delete", new_callable=AsyncMock) as redis_delete:
            await delete_session(7)
        redis_delete.assert_awaited_once_with("bot:session:7")


if __name__ == "__main__":
    unittest.main()
