from datetime import datetime

from sqlalchemy import ForeignKey, String, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.user import User


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Which order this payment is for
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id")
    )

    # Who is paying
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # Payment amount
    amount: Mapped[float] = mapped_column(
        Numeric(10, 2)
    )

    # Currency code (e.g. "INR", "USD")
    currency: Mapped[str] = mapped_column(
        String(10),
        default="INR"
    )

    # Payment method (e.g. "card", "upi", "wallet")
    method: Mapped[str] = mapped_column(
        String(30),
        nullable=True
    )

    # Which gateway processed it
    gateway: Mapped[str] = mapped_column(
        String(30),
        default="stripe"
    )

    # The ID returned by Stripe/Razorpay
    gateway_payment_id: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    # Raw status from the gateway
    gateway_status: Mapped[str] = mapped_column(
        String(50),
        nullable=True
    )

    # Our internal status
    # PENDING / SUCCESS / FAILED / REFUNDED
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING"
    )

    # Timestamps
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
    order: Mapped["Order"] = relationship(
        back_populates="payments"
    )

    user: Mapped["User"] = relationship(
        back_populates="payments"
    )