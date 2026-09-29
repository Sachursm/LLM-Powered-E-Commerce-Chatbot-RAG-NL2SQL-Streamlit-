"""Semantic route coverage and intent-boundary checks.

These tests use the configured local Hugging Face model; no routing API or
Telegram update is involved.
"""

import unittest
from unittest.mock import patch

from bot.config import settings
from bot.router.routes import ROUTE_UTTERANCES
from bot.router.semantic import classify_intent


POSITIVE_CASES = {
    "PRODUCT_SEARCH": (
        "show products",
        "find red Nike sneakers below five thousand rupees",
        "I need men's running footwear in size nine",
        "browse discounted Bluetooth headphones",
        "what black formal shoes are available for under 3000",
        "search the catalog for Puma sports shoes",
    ),
    "PRODUCT_DETAIL": (
        "what is the listed price for product number 25",
        "check the stock available for this specific shoe",
        "tell me the specifications and rating of this item",
        "is item 42 currently in stock",
        "give me more information about this product I selected",
    ),
    "CATEGORY": (
        "list every category in the shop",
        "which product sections can I browse",
        "find the items that belong to electronics",
        "what kinds of products are under footwear",
        "browse everything in the home appliances section",
    ),
    "CART": (
        "let me see the items in my basket",
        "put product 25 into my shopping cart",
        "take the blue shirt out of my cart",
        "set the cart quantity for this item to three",
        "what have I added to my basket so far",
    ),
    "ORDER": (
        "checkout my cart",
        "submit a purchase for the products I selected",
        "I am ready to place this order",
        "buy the contents of my cart now",
        "start a new purchase with these items",
    ),
    "ORDER_STATUS": (
        "where is my latest purchase right now",
        "check the delivery status for order number 15",
        "list the purchases I made recently",
        "when should package 25 reach my address",
        "has my order left the warehouse",
    ),
    "ORDER_CANCEL": (
        "cancel my order",
        "please cancel order number 15 for me",
        "I no longer want my latest purchase",
        "stop processing my order",
        "withdraw the order I just submitted",
        "cancel my purchase before it ships",
    ),
    "PAYMENT": (
        "check the transaction status for my order",
        "the checkout payment did not go through",
        "I have paid but my order still says unpaid",
        "send me the payment link for order 18",
        "was my last payment successful",
    ),
    "ADDRESS": (
        "list the shipping addresses saved to my account",
        "save a new delivery location for me",
        "change the address used for delivery",
        "remove my old home address",
        "make this my default shipping location",
    ),
    "RETURN": (
        "start a return for the damaged item I received",
        "I need to send this product back",
        "request a refund for my purchase",
        "show the return cases I have opened",
        "the seller sent me the wrong item and I want a return",
    ),
    "REVIEW": (
        "write feedback about the shoes I purchased",
        "give item 25 a five star rating",
        "show customer opinions for this product",
        "change the review I posted last week",
        "remove my feedback from this product page",
    ),
    "FAQ": (
        "can I cancel my order?",
        "what kinds of cards can I use to pay",
        "how many days does standard shipping usually take",
        "is delivery free for every customer",
        "what are the store rules for returning items",
        "where can I contact the support team",
    ),
    "ACCOUNT": (
        "show the profile information on my account",
        "edit my personal details",
        "I need to reset my account password",
        "please close and deactivate my account",
        "reactivate my account that was disabled",
    ),
    "SELLER_PRODUCT": (
        "show my products",
        "list the products in my seller inventory",
        "create a listing for a new item in my shop",
        "raise the price of one of my listed products",
        "change the stock count on my store listing",
        "delete a product from my seller catalog",
    ),
    "SELLER_ORDER": (
        "show the orders customers placed for my products",
        "which of my shop's orders still need shipping",
        "open the details for one of my sales",
        "get the bill for an order from my store",
        "ship a customer purchase from my seller account",
    ),
    "SELLER_PAYOUT": (
        "show the payout history for my shop",
        "what amount is owed to me as a seller",
        "when should my next seller payment arrive",
        "update the bank account where my sales are paid",
        "tell me the platform commission charged on my sales",
    ),
    "ADMIN": (
        "open the platform administrator dashboard",
        "list all customer accounts for management",
        "show the system's audit history",
        "review every order across the platform",
        "change the commission percentage for this seller",
    ),
    "DELIVERY_HUB": (
        "list the distribution centers we operate",
        "create a new parcel hub",
        "edit the details of delivery center 4",
        "who manages this delivery hub",
        "show parcels waiting at the hub",
    ),
    "DELIVERY_AGENT": (
        "list our courier drivers",
        "show the packages assigned to my driver account",
        "what deliveries am I assigned to today",
        "find the courier assigned to package 88",
        "show all active delivery staff members",
    ),
    "DELIVERY_OPERATION": (
        "record shipment 10 entering the distribution hub",
        "send shipment 10 out from the hub",
        "assign package 15 to courier number 4",
        "mark package 15 as delivered to the customer",
        "record that delivery attempt 15 failed",
    ),
    "GENERAL_CHAT": (
        "hey there, how is it going",
        "good afternoon",
        "thanks for your help",
        "who am I chatting with",
        "see you later, goodbye",
    ),
    "IMAGE": (
        "I attached a photo of the damaged parcel",
        "please inspect the picture of this product",
        "read the information printed on this invoice image",
        "I want to upload a photo for my product listing",
        "this attached image shows the wrong item I received",
    ),
}


CONFUSING_CASES = (
        ("what payment methods do you accept", "FAQ"),
        ("what is the payment status of order 15", "PAYMENT"),
        ("where is order 15", "ORDER_STATUS"),
        ("cancel order 15", "ORDER_CANCEL"),
        ("what is the cancellation policy", "FAQ"),
        ("can I cancel an order?", "FAQ"),
        ("can I cancel my order?", "FAQ"),
        ("cancel my order", "ORDER_CANCEL"),
        ("show shoes under 5000", "PRODUCT_SEARCH"),
        ("show products", "PRODUCT_SEARCH"),
        ("show my products", "SELLER_PRODUCT"),
        ("tell me about product 25", "PRODUCT_DETAIL"),
        ("show my products that I sell", "SELLER_PRODUCT"),
        ("show products in the shoes category", "CATEGORY"),
        ("show my orders", "ORDER_STATUS"),
        ("show orders for products in my shop", "SELLER_ORDER"),
        ("show all orders across the platform", "ADMIN"),
        ("take shipment 15 for delivery", "DELIVERY_OPERATION"),
        ("show shipments assigned to me as a courier", "DELIVERY_AGENT"),
        ("how do returns work under your policy", "FAQ"),
        ("I want to return the item I purchased", "RETURN"),
)


class SemanticRouterTests(unittest.TestCase):
    def test_five_examples_per_intent(self) -> None:
        self.assertEqual(set(ROUTE_UTTERANCES), set(POSITIVE_CASES))
        for intent, queries in POSITIVE_CASES.items():
            self.assertGreaterEqual(len(queries), 5)
            for query in queries:
                with self.subTest(intent=intent, query=query):
                    result = classify_intent(query)
                    self.assertEqual(result["intent"], intent)
                    self.assertIsInstance(result["confidence"], float)
                    self.assertGreaterEqual(result["confidence"], -1.0)
                    self.assertLessEqual(result["confidence"], 1.0)
                    self.assertEqual(result["query"], query)

    def test_confusing_intent_boundaries(self) -> None:
        for query, expected_intent in CONFUSING_CASES:
            with self.subTest(query=query):
                self.assertEqual(classify_intent(query)["intent"], expected_intent)

    def test_blank_query_is_unknown_without_invented_confidence(self) -> None:
        self.assertEqual(
            classify_intent("   "),
            {"intent": "UNKNOWN", "confidence": None, "query": "   "},
        )

    def test_low_confidence_result_falls_back_to_unknown(self) -> None:
        with patch.object(settings, "ROUTER_CONFIDENCE_THRESHOLD", 1.0):
            result = classify_intent("show me Nike shoes under 5000")
        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertIsInstance(result["confidence"], float)
        self.assertLess(result["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
