"""Tests that conversational wording never pollutes product API searches."""

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-token")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from bot.agent.product_search import _initial_context
from bot.tools.product_search import (
    build_product_search_tools,
    clean_product_search_query,
    extract_search_expression,
)


def empty_page() -> dict:
    return {
        "status": 200,
        "data": {"items": [], "total": 0, "skip": 0, "limit": 20, "has_more": False},
    }


class ProductQueryCleanupTests(unittest.TestCase):
    def test_query_cleanup_examples(self):
        cases = (
            ("laptop", None, "laptop"),
            ("i am looking for a laptop", None, "laptop"),
            ("gaming i am looking for a laptop", "laptop", "gaming laptop"),
            ("casual shoes", "shoes", "casual shoes"),
            ("shoes for men", "shoes", "shoes for men"),
            ("Adidas shoes", "Nike shoes", "Adidas shoes"),
            (
                "laptop no preferences electronics what do you have",
                "laptop",
                "laptop",
            ),
            ("any kind", "keyboard", "keyboard"),
            ("show me more", "boots", "boots"),
            ("do you have Nike shoes?", None, "Nike shoes"),
            ("show me gaming keyboard under 5000", None, "gaming keyboard"),
            ("what do you have", None, None),
        )
        for raw_query, seed, expected in cases:
            with self.subTest(raw_query=raw_query):
                self.assertEqual(clean_product_search_query(raw_query, seed), expected)

    def test_legacy_pending_search_is_normalized_before_refinement(self):
        pending = {
            "intent": "PRODUCT_SEARCH",
            "waiting_for": "product_type",
            "context": {"query": "i am looking for a keyboard"},
        }
        context = _initial_context("gaming", pending)
        self.assertEqual(context["query"], "gaming keyboard")

    def test_request_framing_and_price_are_extracted_separately(self):
        self.assertEqual(extract_search_expression("do you have Nike shoes?"), "Nike shoes")
        self.assertEqual(extract_search_expression("show me gaming keyboard under 5000"), "gaming keyboard")


class ProductToolQueryTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, llm_query, *, query_seed=None, force_query_seed=False, max_price=None):
        api = AsyncMock(return_value=empty_page())
        tool = build_product_search_tools(
            "test-access-token",
            query_seed=query_seed,
            force_query_seed=force_query_seed,
        )[1]
        arguments = {"query": llm_query}
        if max_price is not None:
            arguments["max_price"] = max_price
        with patch("bot.tools.product_search.api_get", api):
            await tool.ainvoke(arguments)
        return api

    async def test_no_preference_uses_existing_query_and_logs_model_vs_api_query(self):
        with self.assertLogs("bot.tools.product_search", level="INFO") as captured:
            api = await self.invoke(
                "laptop no preferences electronics what do you have",
                query_seed="laptop",
            )
        self.assertEqual(api.await_args.kwargs["params"]["search"], "laptop")
        logs = "\n".join(captured.output)
        self.assertIn("PRODUCT_SEARCH_LLM_QUERY=laptop no preferences electronics what do you have", logs)
        self.assertIn("PRODUCT_SEARCH_API_QUERY=laptop", logs)

    async def test_no_context_question_does_not_add_a_search_filter(self):
        api = await self.invoke("what do you have")
        self.assertNotIn("search", api.await_args.kwargs["params"])

    async def test_continuation_query_seed_is_clean_and_price_remains_a_filter(self):
        api = await self.invoke(
            "gaming i am looking for a keyboard",
            query_seed="gaming keyboard",
            force_query_seed=True,
            max_price=5000,
        )
        params = api.await_args.kwargs["params"]
        self.assertEqual(params["search"], "gaming keyboard")
        self.assertEqual(params["max_price"], 5000)

    async def test_product_refinements_reach_api_as_product_terms_only(self):
        cases = (
            ("laptop", None, "laptop"),
            ("casual shoes", "shoes", "casual shoes"),
            ("shoes for men", "shoes", "shoes for men"),
            ("Adidas shoes", "Nike shoes", "Adidas shoes"),
            ("do you have Nike shoes?", None, "Nike shoes"),
        )
        for llm_query, seed, expected in cases:
            with self.subTest(llm_query=llm_query):
                api = await self.invoke(llm_query, query_seed=seed)
                self.assertEqual(api.await_args.kwargs["params"]["search"], expected)


if __name__ == "__main__":
    unittest.main()
