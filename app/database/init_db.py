import asyncio

from app.database.database import Base, engine

# Import every model so SQLAlchemy registers
# every table with Base.metadata.
from app.database.models import (
    User,
    Category,
    Product,
    Order,
    OrderItem,
    Cart,
    CartItem,
    SellerProduct,
    AuditLog,
    ReactivationRequest,
)


async def init_db():
    # Open an asynchronous database connection.
    async with engine.begin() as conn:

        # Run SQLAlchemy's normal table creation
        # through the asynchronous connection.
        await conn.run_sync(
            Base.metadata.create_all
        )

    # Close the async engine after initialization.
    await engine.dispose()


if __name__ == "__main__":
    # Start the asynchronous database initialization.
    asyncio.run(init_db())

    print("Database tables created")