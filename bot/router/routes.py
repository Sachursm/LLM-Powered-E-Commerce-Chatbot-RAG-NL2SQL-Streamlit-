"""High-level user-intent routes and example utterances.

These names describe what a user appears to want. They intentionally do not
contain API endpoint names, tool names, business logic, or authorization rules.
"""

import re
from types import MappingProxyType


ROUTE_UTTERANCES = MappingProxyType(
    {
        "PRODUCT_SEARCH": (
            "show me shoes under 5000",
            "find Nike shoes",
            "Nike shoes below 3000",
            "running shoes for men",
            "black formal shoes size 9",
            "show Adidas shoes between 2000 and 5000",
            "do you have Puma running shoes",
            "find products under 1000",
            "show me discounted shoes",
            "browse the latest headphones",
            "show discounted wireless headphones",
            "show products",
            "browse all products in the marketplace",
            "find something",
            "what products are available",
            "show me shoes",
            "do you have electronics",
            "find something under 5000",
            "search for a keyboard",
            "do you have a keyboard",
            "show laptops",
            "find a Bluetooth mouse",
            "what products do I have",
            "what are the products you have",
        ),
        "PRODUCT_DETAIL": (
            "tell me about product 25",
            "what are the details of this product",
            "how much does this product cost",
            "how many are in stock for this item",
            "show me the details of this shoe",
            "what is this product's rating",
            "is this product available right now",
            "give me the specifications for this item",
        ),
        "CATEGORY": (
            "show me all product categories",
            "what categories do you have",
            "show electronics products",
            "what products are in the shoes category",
            "list the available categories",
            "which categories are available in the store",
            "which product sections can I browse",
            "browse products in the home appliances category",
            "show items from the clothing category",
        ),
        "CART": (
            "show my cart",
            "add this shoe to my cart",
            "add product 25 to my cart",
            "remove this item from my cart",
            "remove product 10 from my cart",
            "change the quantity to 3 in my cart",
            "update my cart",
            "what is currently in my shopping cart",
            "remove the blue shirt from my basket",
            "which items are currently in my basket",
            "view the contents of my shopping basket",
            "show the things I added to my cart",
        ),
        "ORDER": (
            "place an order",
            "I want to buy these products",
            "create my order",
            "checkout my cart",
            "place my order now",
            "I want to purchase this item",
            "complete the purchase in my cart",
            "submit this order for me",
            "complete checkout for the items in my basket",
            "finish checking out and place my order",
            "submit the items in my cart as a new order",
            "I am ready to buy these items now",
            "please submit this purchase",
            "start a new purchase with these items",
        ),
        "ORDER_STATUS": (
            "where is my order",
            "track my order",
            "what is the status of order 15",
            "when will my order arrive",
            "show my orders",
            "what orders have I placed",
            "track order 25",
            "has my package been shipped yet",
            "check the delivery progress for my purchase",
            "check where order number 15 is in delivery",
            "show my recent purchases",
            "has my order been dispatched yet",
            "check the delivery status for order number 15",
        ),
        "ORDER_CANCEL": (
            "cancel my order",
            "I want to cancel order 15",
            "cancel my latest order",
            "I do not want this order anymore",
            "please stop my order from being processed",
            "withdraw my order number 25",
            "I changed my mind and want to cancel my purchase",
            "cancel the order I just placed",
            "please cancel my order now",
        ),
        "PAYMENT": (
            "what is the payment status of order 15",
            "did my payment succeed",
            "my payment failed",
            "I paid but the order is still unpaid",
            "where is my payment link",
            "create a payment link for this order",
            "check whether transaction 42 was paid",
            "the payment for my order is pending",
        ),
        "ADDRESS": (
            "show my saved addresses",
            "add a new delivery address",
            "change my delivery address",
            "delete my old address",
            "update my address details",
            "set this address as my default",
            "what address do I have saved",
            "I need to edit my shipping address",
        ),
        "RETURN": (
            "I want to return my product",
            "request a return for this item",
            "my product arrived damaged",
            "I received the wrong product",
            "I want a refund for this purchase",
            "can I return this item I bought",
            "show my return requests",
            "list the return requests I submitted",
            "start a return for order item 12",
            "list my existing return applications",
        ),
        "REVIEW": (
            "write a review for this product",
            "I want to rate this product",
            "give this product five stars",
            "show reviews for product 25",
            "what are people saying about this product",
            "edit my review for this item",
            "delete my product review",
            "leave feedback about the shoes I bought",
            "edit my review from last week",
            "delete the feedback I left on this product",
        ),
        "FAQ": (
            "what payment methods do you support",
            "do you accept UPI or debit cards",
            "which bank cards can I use at checkout",
            "can I pay with cash on delivery",
            "how long does delivery usually take",
            "do you offer free shipping",
            "do you ship internationally to Canada",
            "what is your return policy and how many days do I have",
            "how long does a refund take under your policy",
            "how can I contact customer support",
            "how does your ecommerce service work",
            "what is your cancellation policy",
            "can I cancel an order",
            "can I cancel my order",
            "what are the rules for canceling an order",
            "what rules apply when sending an item back",
            "explain the shop's return rules to me",
        ),
        "ACCOUNT": (
            "show my account profile",
            "update my profile information",
            "change my password",
            "deactivate my account",
            "I want to change my account details",
            "request account reactivation",
            "update the name on my profile",
            "show my personal account information",
            "restore access to my disabled profile",
        ),
        "SELLER_PRODUCT": (
            "show my products",
            "show my seller products",
            "remove a product from my seller catalog",
            "delete my product listing",
            "show products that I sell",
            "what products do I sell",
            "list all the items in my shop",
        ),
        "PRODUCT_CREATE": (
            "add a new product",
            "create a new product",
            "create a new product listing for my shop",
            "add a product to my seller catalog",
            "I want to sell a new item",
            "list a new item for sale",
            "add a new item to the store",
            "upload a new product to the catalog",
            "put a new product up for sale",
            "add new shoes to the catalog",
            "add a new laptop to my shop catalog",
            "create a product called Puma Runner priced 2999",
            "create product Samsung earbuds with price 1999 and stock 10",
        ),
        "PRODUCT_UPDATE": (
            "update a product",
            "edit a product",
            "update the price of my listed product",
            "change stock for one of my products",
            "edit my shop's product listing",
            "adjust the inventory quantity on my product page",
            "update product 25",
            "change the description of product 12",
            "change the category of my product",
            "change the image of my product",
            "set the price of product 40 to 2999",
        ),
        "SELLER_ORDER": (
            "show orders for products I sell",
            "show my seller orders",
            "what customer orders do I need to ship",
            "show the orders placed for my shop",
            "get the shipping bill for my customer order",
            "ship order 15 from my seller account",
            "which orders are pending shipment for my products",
            "show the order details for one of my sales",
        ),
        "SELLER_PAYOUT": (
            "show my seller payouts",
            "how much money will I receive as a seller",
            "show my payout summary",
            "when will I get my seller payout",
            "show my bank details as a seller",
            "update my seller bank details",
            "what commission rate applies to my sales",
            "how much has been paid out to my shop",
            "what fee does the marketplace deduct from my sales",
        ),
        "ADMIN": (
            "show the admin dashboard",
            "show all users in the system",
            "manage user accounts as an administrator",
            "show audit logs for the platform",
            "show every payment in the system",
            "show all platform orders",
            "show all return requests for administration",
            "approve this return request as admin",
            "reject a customer's return request",
            "process the seller payout",
            "set the commission rate for seller 12",
            "go to the site management dashboard",
            "display every customer profile for review",
            "show the platform's activity log",
        ),
        "DELIVERY_HUB": (
            "show delivery hubs",
            "create a delivery hub",
            "update this hub's information",
            "show the managers assigned to a hub",
            "assign a manager to this delivery hub",
            "show shipments currently at this hub",
            "list all of our distribution hubs",
            "remove a hub manager from this location",
            "change the information for distribution location 4",
            "edit the configuration for hub number 4",
            "update the parcel depot details",
            "edit the details of delivery center 4",
        ),
        "DELIVERY_AGENT": (
            "show the delivery agents",
            "list all delivery drivers",
            "show shipments assigned to me as a delivery agent",
            "what delivery assignments do I have",
            "show my assigned deliveries",
            "which packages am I responsible for delivering",
            "find the delivery agent assigned to this package",
            "show the active delivery staff",
            "list parcels assigned to me as a driver",
        ),
        "DELIVERY_OPERATION": (
            "ship shipment 10 into the hub",
            "ship shipment 10 out of the hub",
            "assign shipment 15 to delivery agent 4",
            "take shipment 15 for delivery",
            "mark shipment 15 as delivered",
            "mark shipment 15 as a failed delivery",
            "record that package 22 arrived at the hub",
            "send package 22 from the hub to its next destination",
            "assign this parcel to an agent for delivery",
            "report a failed delivery attempt for this package",
            "mark delivery attempt number 15 unsuccessful",
        ),
        "GENERAL_CHAT": (
            "hello",
            "hi there",
            "hey",
            "who are you",
            "what can you do",
            "help me",
            "thanks a lot",
            "goodbye",
            "good morning",
            "how are you doing",
            "I appreciate your help",
            "who is this assistant",
            "talk to you later, bye",
            "who am I talking to",
        ),
        "IMAGE": (
            "here is the product image",
            "this is a picture of the damaged product",
            "here is the shipping bill image",
            "read the text from this bill photo",
            "I want to upload an image for my product listing",
            "please check this image of the damaged item",
            "the attached photo shows the wrong item I received",
            "I am sending a picture of my package label",
            "take a look at this product photo",
            "extract the text visible on this invoice picture",
            "the photo I attached shows that the wrong item arrived",
        ),
    }
)


ROUTE_DESCRIPTIONS = MappingProxyType(
    {
        "PRODUCT_SEARCH": "Browse or filter the product catalog.",
        "PRODUCT_DETAIL": "Ask for information about a specific product.",
        "CATEGORY": "Browse product categories or products within a category.",
        "CART": "Ask to view or change the shopping cart.",
        "ORDER": "Create or check out an order.",
        "ORDER_STATUS": "Ask about the user's existing orders or delivery status.",
        "ORDER_CANCEL": "Ask to cancel a specific or recent order.",
        "PAYMENT": "Ask about the status or link for a specific transaction.",
        "ADDRESS": "View or manage saved delivery addresses.",
        "RETURN": "Request, view, or discuss a return/refund transaction.",
        "REVIEW": "Create, view, edit, or delete a product review.",
        "FAQ": "Ask about general store policies or service information.",
        "ACCOUNT": "View or manage the authenticated user's account.",
        "SELLER_PRODUCT": "View or remove product listings owned by the seller.",
        "PRODUCT_CREATE": "Create a new product listing in the catalog.",
        "PRODUCT_UPDATE": "Change the details of an existing product listing.",
        "SELLER_ORDER": "View or handle orders associated with the seller's products.",
        "SELLER_PAYOUT": "Ask about seller payouts, bank details, or commission.",
        "ADMIN": "Ask for administrative platform management information or actions.",
        "DELIVERY_HUB": "Manage delivery hubs and hub manager information.",
        "DELIVERY_AGENT": "Ask about delivery agents or the user's assignments.",
        "DELIVERY_OPERATION": "Ask to change shipment or delivery workflow state.",
        "GENERAL_CHAT": "Greeting, thanks, or general conversational message.",
        "IMAGE": "Text indicates an attached image needs later OCR or vision handling.",
    }
)


# Only genuinely ambiguous catalog phrases depend on role context. Clear
# marketplace wording (for example, "browse products") stays PRODUCT_SEARCH.
# This affects intent classification only; it grants no API permissions.
ROLE_DISAMBIGUATION = MappingProxyType(
    {
        "show products": MappingProxyType(
            {"default": "PRODUCT_SEARCH", "SELLER": "SELLER_PRODUCT"}
        ),
        "show my products": MappingProxyType(
            {"default": "PRODUCT_SEARCH", "SELLER": "SELLER_PRODUCT"}
        ),
        "what products do i have": MappingProxyType(
            {"default": "PRODUCT_SEARCH", "SELLER": "SELLER_PRODUCT"}
        ),
        "browse products": MappingProxyType({"default": "PRODUCT_SEARCH"}),
    }
)


# Product create/update commands carry brand, price and category words that pull
# the embedding match toward search or category, so a clear command shape is
# matched first. Messages about carts, orders, reviews or accounts never match.
_NOT_A_LISTING_CHANGE = re.compile(
    r"\b(?:cart|basket|wishlist|orders?|reviews?|ratings?|feedback|address|profile|password|account)\b",
    re.IGNORECASE,
)
COMMAND_PATTERNS = (
    (
        "PRODUCT_CREATE",
        re.compile(
            r"^(?:please\s+)?(?:i\s+(?:want|would like)\s+to\s+)?"
            r"(?:(?:create|add|upload)\s+(?:a\s+|an\s+)?(?:new\s+)?|list\s+(?:a\s+)?new\s+)"
            r"(?:products?|items?|listings?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "PRODUCT_UPDATE",
        re.compile(
            r"^(?:please\s+)?(?:update|edit|change|modify|set|raise|lower|increase|decrease)\b"
            r"(?=.*\b(?:products?|listings?)\b)"
            r"(?=.*\b(?:price|stock|inventory|description|category|image|photo|name|title|details)\b)",
            re.IGNORECASE,
        ),
    ),
)


def match_command_intent(text: str) -> str | None:
    """Return the intent for a clear product create/update command, if any."""
    if _NOT_A_LISTING_CHANGE.search(text):
        return None
    stripped = text.strip()
    return next((intent for intent, pattern in COMMAND_PATTERNS if pattern.search(stripped)), None)
