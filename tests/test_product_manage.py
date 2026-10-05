"""Deterministic tests for the product create/update draft, confirmation and submit."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-token")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from bot.agent.conversation import resolve_message_intent
from bot.agent.product_manage import run_product_manage_turn
from bot.handlers.product_manage import _after_photo, confirm_keyboard
from bot.router.semantic import role_may_run
from bot.services import image_upload
from bot.tools.product_manage import submit_product_change
from tests.test_product_search import FakeGroqClient, category_page, groq_reply

CATEGORIES = category_page(["Shoes", "Electronics", "Clothing"])
_patches = (
    patch("bot.tools.product_search.get_cached_categories", AsyncMock(return_value=None)),
    patch("bot.tools.product_search.cache_categories", AsyncMock()),
)


def setUpModule():
    for item in _patches:
        item.start()


def tearDownModule():
    for item in _patches:
        item.stop()


def product(product_id=12, **overrides):
    row = {
        "id": product_id, "source_product_id": None, "name": "Nike Air Zoom",
        "description": "Running shoe", "price": 4999, "stock": 20,
        "image_url": "https://img.test/a.jpg,https://img.test/b.jpg",
        "rating": None, "ratings_count": None, "category_id": 1, "seller_id": 7,
    }
    return {**row, **overrides}


FULL_CREATE_ARGS = {
    "name": "Nike Air Zoom", "description": "Lightweight running shoe", "price": 4999,
    "stock": 20, "category": "shoes", "image_url": "https://img.test/zoom.jpg",
}


class CreateDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_message_asks_for_confirmation_without_writing(self):
        fake = FakeGroqClient([groq_reply(tool_calls=[("c-1", "create_product_tool", FULL_CREATE_ARGS)])])
        get = AsyncMock(return_value=CATEGORIES)
        post = AsyncMock()
        with patch("bot.tools.product_search.api_get", get), patch("bot.tools.product_manage.api_post", post):
            turn = await run_product_manage_turn(
                "add Nike Air Zoom ...", "secret-jwt", "SELLER", "PRODUCT_CREATE", groq_client=fake,
            )
        post.assert_not_awaited()
        self.assertTrue(turn.needs_confirmation)
        self.assertEqual(turn.pending_workflow["draft"]["category"], "Shoes")
        self.assertIn("Please confirm the new product", turn.answer)
        self.assertIn("₹4,999", turn.answer)
        self.assertEqual(len(fake.requests), 1)
        self.assertNotIn("secret-jwt", json.dumps(fake.requests, default=str))
        self.assertIsNotNone(confirm_keyboard(turn.pending_workflow))

    async def test_missing_fields_are_requested_then_kept_across_turns(self):
        fake = FakeGroqClient([
            groq_reply(tool_calls=[("c-1", "create_product_tool", {"name": "Nike Air Zoom", "price": 4999})]),
            groq_reply(tool_calls=[("c-2", "create_product_tool", {
                "description": "Running shoe", "stock": 5, "category": "Shoes",
                "image_url": "https://img.test/z.jpg",
            })]),
        ])
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=CATEGORIES)):
            first = await run_product_manage_turn(
                "add a product Nike Air Zoom for 4999", "jwt", "ADMIN", "PRODUCT_CREATE", groq_client=fake,
            )
            self.assertIn("description", first.answer)
            self.assertIn("product photo", first.answer)
            self.assertEqual(first.pending_workflow["waiting_for"], "fields")
            second = await run_product_manage_turn(
                "running shoe, 5 in stock, shoes, https://img.test/z.jpg", "jwt", "ADMIN", "PRODUCT_CREATE",
                pending_workflow=first.pending_workflow, groq_client=fake,
            )
        self.assertTrue(second.needs_confirmation)
        self.assertEqual(second.pending_workflow["draft"]["name"], "Nike Air Zoom")

    async def test_unknown_category_names_it_and_lists_real_categories(self):
        fake = FakeGroqClient([groq_reply(tool_calls=[("c-1", "create_product_tool", {
            **FULL_CREATE_ARGS, "category": "Footwear",
        })])])
        with patch("bot.tools.product_search.api_get", AsyncMock(return_value=CATEGORIES)):
            turn = await run_product_manage_turn("...", "jwt", "SELLER", "PRODUCT_CREATE", groq_client=fake)
        self.assertIn('Category "Footwear" not found', turn.answer)
        self.assertIn("The closest are: Shoes", turn.answer)
        self.assertNotIn("category", turn.pending_workflow["draft"])
        self.assertEqual(turn.pending_workflow["draft"]["price"], 4999)
        self.assertFalse(turn.needs_confirmation)

    async def test_invalid_price_is_explained(self):
        fake = FakeGroqClient([groq_reply(tool_calls=[("c-1", "create_product_tool", {"price": -5})])])
        turn = await run_product_manage_turn("price -5", "jwt", "SELLER", "PRODUCT_CREATE", groq_client=fake)
        self.assertIn("greater than 0", turn.answer)

    async def test_cancel_clears_the_draft_without_an_llm_call(self):
        fake = FakeGroqClient([])
        turn = await run_product_manage_turn(
            "cancel", "jwt", "SELLER", "PRODUCT_CREATE",
            pending_workflow={"intent": "PRODUCT_CREATE", "draft": {"name": "X"}, "waiting_for": "fields"},
            groq_client=fake,
        )
        self.assertIsNone(turn.pending_workflow)
        self.assertEqual(fake.requests, [])

    async def test_typed_yes_does_not_save_and_reshows_buttons(self):
        pending = {
            "intent": "PRODUCT_CREATE", "draft": {**FULL_CREATE_ARGS, "category": "Shoes"},
            "waiting_for": "confirmation", "confirm_id": "abcd1234",
        }
        fake = FakeGroqClient([groq_reply(content="Your product has been created!")])
        turn = await run_product_manage_turn(
            "yes", "jwt", "SELLER", "PRODUCT_CREATE", pending_workflow=pending, groq_client=fake,
        )
        self.assertNotIn("created!", turn.answer)
        self.assertIn("use the buttons", turn.answer)
        self.assertTrue(turn.needs_confirmation)
        self.assertNotEqual(turn.pending_workflow["confirm_id"], "abcd1234")


class UpdateDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_seller_update_by_id_shows_old_and_new_values(self):
        fake = FakeGroqClient([groq_reply(tool_calls=[("u-1", "update_product_tool", {"product_id": 12, "price": 4500})])])

        async def api_get(endpoint, token=None, params=None):
            return {"status": 200, "data": [product()]} if endpoint == "/seller/products/" else CATEGORIES

        with patch("bot.tools.product_manage.api_get", AsyncMock(side_effect=api_get)), \
                patch("bot.tools.product_search.api_get", AsyncMock(return_value=CATEGORIES)):
            turn = await run_product_manage_turn(
                "change price of product 12 to 4500", "jwt", "SELLER", "PRODUCT_UPDATE", groq_client=fake,
            )
        self.assertTrue(turn.needs_confirmation)
        self.assertIn("Price: ₹4,999 → ₹4,500", turn.answer)
        self.assertEqual(turn.pending_workflow["draft"], {"price": 4500.0})

    async def test_seller_cannot_pick_a_product_they_do_not_own(self):
        fake = FakeGroqClient([groq_reply(tool_calls=[("u-1", "update_product_tool", {"product_id": 99, "stock": 3})])])
        with patch("bot.tools.product_manage.api_get", AsyncMock(return_value={"status": 200, "data": [product()]})):
            turn = await run_product_manage_turn("update product 99", "jwt", "SELLER", "PRODUCT_UPDATE", groq_client=fake)
        self.assertIn("#99 isn't in your listings", turn.answer)
        self.assertEqual(turn.pending_workflow["waiting_for"], "product")

    async def test_ambiguous_name_lists_matches(self):
        fake = FakeGroqClient([groq_reply(tool_calls=[("u-1", "update_product_tool", {"product_name": "Nike", "stock": 3})])])
        owned = [product(1, name="Nike Air Zoom"), product(2, name="Nike Pegasus"), product(3, name="Puma Runner")]
        with patch("bot.tools.product_manage.api_get", AsyncMock(return_value={"status": 200, "data": owned})):
            turn = await run_product_manage_turn("update Nike stock to 3", "jwt", "SELLER", "PRODUCT_UPDATE", groq_client=fake)
        self.assertIn("#1 Nike Air Zoom", turn.answer)
        self.assertIn("#2 Nike Pegasus", turn.answer)
        self.assertNotIn("Puma", turn.answer)
        self.assertEqual(turn.pending_workflow["draft"], {"stock": 3})


class SubmitTests(unittest.IsolatedAsyncioTestCase):
    create_pending = {
        "intent": "PRODUCT_CREATE", "draft": {**FULL_CREATE_ARGS, "category": "Shoes"},
        "waiting_for": "confirmation", "confirm_id": "abcd",
    }

    async def test_endpoint_depends_on_role(self):
        for role, endpoint in (("ADMIN", "/products/"), ("SELLER", "/seller/products/")):
            post = AsyncMock(return_value={"status": 201, "data": product(812)})
            with self.subTest(role=role), patch("bot.tools.product_manage.api_post", post):
                answer, reopened = await submit_product_change("jwt", role, self.create_pending)
                self.assertEqual(post.await_args.args[0], endpoint)
                self.assertEqual(post.await_args.kwargs["data"]["category"], "Shoes")
                self.assertIn("Created product #812", answer)
                self.assertIsNone(reopened)

    async def test_user_role_is_refused_without_an_api_call(self):
        post = AsyncMock()
        with patch("bot.tools.product_manage.api_post", post):
            answer, _ = await submit_product_change("jwt", "USER", self.create_pending)
        post.assert_not_awaited()
        self.assertIn("permission", answer)

    async def test_api_category_not_found_names_the_category_and_reopens_draft(self):
        post = AsyncMock(return_value={"status": 404, "data": {"detail": "Category not found"}})
        with patch("bot.tools.product_manage.api_post", post), \
                patch("bot.tools.product_search.api_get", AsyncMock(return_value=category_page(["Electronics", "Sandals"]))):
            answer, reopened = await submit_product_change("jwt", "SELLER", self.create_pending)
        self.assertIn('Category "Shoes" not found', answer)
        self.assertIn("The closest are: Sandals", answer)
        self.assertEqual(reopened["waiting_for"], "fields")
        self.assertNotIn("category", reopened["draft"])

    async def test_update_sends_only_changed_fields(self):
        patch_api = AsyncMock(return_value={"status": 200, "data": product(12, price=4500)})
        pending = {"intent": "PRODUCT_UPDATE", "product_id": 12, "draft": {"price": 4500.0}}
        with patch("bot.tools.product_manage.api_patch", patch_api):
            answer, _ = await submit_product_change("jwt", "SELLER", pending)
        patch_api.assert_awaited_once_with("/seller/products/12", data={"price": 4500.0}, token="jwt")
        self.assertIn("Updated product #12", answer)


class RoutingAndPhotoTests(unittest.IsolatedAsyncioTestCase):
    def test_only_sellers_and_admins_may_run_product_changes(self):
        self.assertTrue(role_may_run("PRODUCT_CREATE", "SELLER"))
        self.assertTrue(role_may_run("PRODUCT_UPDATE", "ADMIN"))
        self.assertFalse(role_may_run("PRODUCT_CREATE", "USER"))
        self.assertTrue(role_may_run("PRODUCT_SEARCH", "USER"))

    async def test_bare_reply_with_open_draft_continues_it(self):
        pending = {"intent": "PRODUCT_CREATE", "draft": {}, "waiting_for": "fields"}
        with patch("bot.agent.conversation.classify_intent", return_value={"intent": "UNKNOWN", "confidence": 0.1, "query": "4999"}), \
                patch("bot.agent.conversation.detect_continuation", AsyncMock(return_value="NO")):
            decision = await resolve_message_intent(
                "4999", "SELLER", pending_workflow=pending,
                previous_user_message="add a product", previous_bot_message="I still need: price.",
            )
        self.assertEqual(decision["intent"], "PRODUCT_CREATE")
        self.assertIs(decision["continuation_context"], pending)

    def test_last_missing_photo_moves_to_confirmation(self):
        draft = {**FULL_CREATE_ARGS, "category": "Shoes", "image_url": "https://img.test/1.jpg"}
        answer, pending = _after_photo("PRODUCT_CREATE", {"intent": "PRODUCT_CREATE", "draft": draft}, 1)
        self.assertIn("Photo added (1 total)", answer)
        self.assertEqual(pending["waiting_for"], "confirmation")

    async def test_upload_is_refused_when_cloudinary_is_not_configured(self):
        with patch.object(image_upload.settings, "CLOUDINARY_CLOUD_NAME", None):
            with self.assertRaises(image_upload.ImageUploadError):
                await image_upload.upload_product_image(b"x")

    def test_cloudinary_signature_matches_documented_format(self):
        # sha1("folder=f&timestamp=1" + "secret")
        self.assertEqual(
            image_upload._signature({"timestamp": "1", "folder": "f"}, "secret"),
            __import__("hashlib").sha1(b"folder=f&timestamp=1secret").hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
