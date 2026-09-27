from datetime import datetime

from sqlalchemy import (
    ForeignKey, String, DateTime,
    Float, Text, UniqueConstraint
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.order import Order


class SellerCommission(Base):
    __tablename__ = "seller_commissions"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True
    )

    # Commission rate (0.15 = 15%)
    rate: Mapped[float] = mapped_column(
        Float,
        default=0.15
    )

    # Admin who set this rate
    set_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
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

    # Relationships
    seller: Mapped["User"] = relationship(
        foreign_keys=[seller_id]
    )


class SellerPayout(Base):
    __tablename__ = "seller_payouts"
    __table_args__ = (
        UniqueConstraint(
            "order_item_id",
            name="uq_seller_payouts_order_item_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id")
    )

    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id")
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id")
    )

    # What customer paid for this item
    sale_amount: Mapped[float] = mapped_column(
        Float
    )

    # Commission rate at time of sale
    commission_rate: Mapped[float] = mapped_column(
        Float
    )

    # Platform keeps this
    commission_amount: Mapped[float] = mapped_column(
        Float
    )

    # Seller receives this
    payout_amount: Mapped[float] = mapped_column(
        Float
    )

    # PENDING → ELIGIBLE → PROCESSING → PAID
    # or ON_HOLD
    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING"
    )

    # When payout becomes eligible
    # (delivery date + 7 days)
    eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    # When admin transferred money
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    # Bank transfer reference
    transaction_ref: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    admin_notes: Mapped[str | None] = mapped_column(
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

    # Relationships
    seller: Mapped["User"] = relationship(
        foreign_keys=[seller_id]
    )

    order: Mapped["Order"] = relationship()
