# objective to find which route to take for a given query
from semantic_router import Route
from semantic_router.routers import SemanticRouter
from semantic_router.encoders import HuggingFaceEncoder



encoder = HuggingFaceEncoder(name="sentence-transformers/all-MiniLM-L6-v2"
                             )
faq = Route(
    name="FAQ",
    utterances=[
    "What payment options do you support?",
    "How can I pay for my order?",
    "Do you accept debit cards?",
    "Can I pay using UPI?",
    "Is cash on delivery available?",
    "Are EMI payments supported?",
    "Can I use net banking?",
    "Do you accept international cards?",
    "Is online payment secure?",
    "Can I pay after delivery?",
    "Are there any discounts right now?",
    "Do you have any promo codes?",
    "How can I get a discount?",
    "Are there bank offers available?",
    "Do you offer card discounts?",
    "Any seasonal sale going on?",
    "Are there student discounts?",
    "Do you have festival offers?",
    "How do I apply a coupon?",
    "Why is my coupon not working?",
    "What is your return policy?",
    "Can I return a product?",
    "How do I request a return?",
    "Is return free?",
    "How many days to return?",
    "When will I get my refund?",
    "How long do refunds take?",
    "Can I exchange instead of return?",
    "What items are non-returnable?",
    "How do I cancel a return?",
    "What are the delivery charges?",
    "Do you offer free shipping?",
    "How long does delivery take?",
    "When will my order arrive?",
    "Do you deliver to my location?",
    "Can I track my order?",
    "Why is my delivery delayed?",
    "Do you have same-day delivery?",
    "What courier do you use?",
    "How do I change delivery address?",
    "How do I cancel my order?",
    "Can I modify my order?",
    "I received a damaged product",
    "Wrong item delivered",
    "Item missing from package",
    "My order failed but money deducted",
    "I didn’t receive confirmation",
    "Order shows delivered but not received",
    "How do I contact support?",
    "Where is my order?",
    "do you ship internationally",
    "do you ship internationally to canada",
    "what payment methods do you accept",
    "do you take cash as a payment method",
    "do you ship to canada"
    ]
)


sql = Route(
    name="SQL",
    utterances=[
        "show me products under 500 rupees",
        "products under 500 rupees",
        "products below 500 rupees",
        "shoes under 500 rupees",
      "I want to buy nike shoes with 50% discount",
        "Show me nike shoes on sale",
        "Do you have discounted nike shoes",
        "Nike shoes under 5000",
        "Nike running shoes price",
        "Are there any shoes under Rs. 3000?",
        "Show shoes below 3000 rupees",
        "Budget shoes under 3k",
        "Cheap shoes under 3000",
        "Shoes in price range 2000 to 3000",
        "Do you have formal shoes in size 9?",
        "Formal shoes size 9",
        "Men formal shoes size 9",
        "Black formal shoes size 9",
        "Office shoes size 9",
        "Are there any Puma shoes on sale?",
        "Puma shoes discount",
        "Show puma shoes offers",
        "Puma sneakers sale",
        "Puma shoes under 4000",
        "What is the price of puma running shoes?",
        "Puma running shoes price",
        "Cost of puma sports shoes",
        "Puma running shoes under 5000",
        "Latest puma running shoes price",
        "Adidas shoes under 4000",
        "Running shoes under 5000",
        "Sports shoes for men under 3000",
        "Casual shoes under 2500",
        "White sneakers under 3500",
        "Size 8 running shoes",
        "Size 10 sports shoes",
        "Men sneakers size 9",
        "Women running shoes size 7",
        "Leather shoes under 6000",
        "Gym shoes under 4000",
        "Walking shoes under 3000",
        "Best running shoes under 5000",
        "Affordable sports shoes",
        "Low price sneakers"
    ]
)

routes = [faq, sql]

rt = SemanticRouter(encoder=encoder, routes=routes , auto_sync="local")

#rt.index()   # 🔑 builds vector index

if __name__ == "__main__":
    pass
    # query = "What payment methods are accepted?"
    # print(rt(query).name)