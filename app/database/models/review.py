from datetime import datetime

from sqlalchemy import (
    ForeignKey, DateTime, Text,
    Integer, UniqueConstraint
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.product import Product


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id")
    )

    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id")
    )

    rating: Mapped[int] = mapped_column(
        Integer
    )

    review_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            'user_id',
            'product_id',
            name='uq_user_product_review'
        ),
    )

    user: Mapped["User"] = relationship()

    product: Mapped["Product"] = relationship()