from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.product import Product
    from app.database.models.user import User


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Order this item belongs to
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id")
    )

    # Product that was purchased
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id")
    )

    # Owner/seller responsible for this product
    #
    # This can point to:
    # - an ADMIN
    # - a SELLER
    #
    # depending on who owns the product.
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # Number of units purchased
    quantity: Mapped[int] = mapped_column(
        Integer
    )

    # Price of ONE unit at the time of purchase
    #
    # We store this separately from Product.price
    # because Product.price may change later.
    unit_price: Mapped[float] = mapped_column(
        Float
    )

    # When this order item was created
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    # Order relationship
    order: Mapped["Order"] = relationship(
        back_populates="items"
    )

    # Product relationship
    product: Mapped["Product"] = relationship()

    # Owner relationship
    owner: Mapped["User"] = relationship()