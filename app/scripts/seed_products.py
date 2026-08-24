import random
import pandas as pd

from app.database.database import SessionLocal
from app.database.models.category import Category
from app.database.models.product import Product

CSV_PATH = "data/Combined_dataset.csv"

def clean_price(value):
    value = str(value)
    value = value.replace("₹", "")
    value = value.replace(",", "")
    value = value.replace('"', "")
    return float(value)

def seed_products():
    df = pd.read_csv(CSV_PATH)
    session = SessionLocal()

    try:
        for _, row in df.iterrows():

            existing_product = (
                session.query(Product)
                .filter(Product.source_product_id == int(row["product_id"]))
                .first()
            )

            if existing_product:
                continue

            category = (
                session.query(Category)
                .filter(Category.name == row["category"])
                .first()
            )

            if category is None:
                category = Category(
                    name=row["category"]
                )
                session.add(category)
                session.flush()

            product = Product(
                source_product_id=int(row["product_id"]),
                name=row["title"],
                description=row["product_description"],
                price=clean_price(row["final_price"]),
                stock=random.randint(10, 100),
                image_url=row["images"],
                rating=float(row["rating"]),
                ratings_count=int(row["ratings_count"]),
                category_id=category.id,
            )

            session.add(product)

        session.commit()

        print("Product seeding completed.")

    except Exception as e:
        session.rollback()
        print(f"Error while importing products: {e}")

    finally:
        session.close()


if __name__ == "__main__":
    seed_products()