from sqlalchemy import select

from app.database.database import SessionLocal
from app.database.models.product import Product


session = SessionLocal()

try:
    stmt = select(Product).limit(5)

    result = session.execute(stmt)

    products = result.scalars().all()

    for product in products:
        print(
            product.id,
            product.name,
            product.price,
            product.stock,
            product.category.name
        )

finally:
    session.close()