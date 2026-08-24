from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.product import Product


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id")
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id")
    )

    quantity: Mapped[int] = mapped_column(
        Integer
    )

    order: Mapped["Order"] = relationship(
        back_populates="items"
    )

    product: Mapped["Product"] = relationship()