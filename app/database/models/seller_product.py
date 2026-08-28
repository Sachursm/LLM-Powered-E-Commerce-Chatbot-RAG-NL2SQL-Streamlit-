from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.product import Product


class SellerProduct(Base):
    __tablename__ = "seller_products"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    seller: Mapped["User"] = relationship(
        back_populates="seller_products"
    )

    product: Mapped["Product"] = relationship(
        back_populates="seller_products"
    )

    __table_args__ = (
        UniqueConstraint(
            "seller_id",
            "product_id",
            name="uq_seller_product"
        ),
    )