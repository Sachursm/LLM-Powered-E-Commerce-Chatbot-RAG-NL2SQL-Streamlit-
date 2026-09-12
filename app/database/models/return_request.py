from datetime import datetime

from sqlalchemy import (
    ForeignKey, String, DateTime, Text
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.user import User
    from app.database.models.shipment import Shipment


class ReturnRequest(Base):
    __tablename__ = "return_requests"

    id: Mapped[int] = mapped_column(
        primary_key=True
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

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # RETURN / REPLACE / EXCHANGE
    type: Mapped[str] = mapped_column(
        String(20)
    )

    # DAMAGED / WRONG_SIZE / DEFECTIVE /
    # WRONG_PRODUCT / OTHER
    reason: Mapped[str] = mapped_column(
        String(30)
    )

    # Customer's message
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # Image URLs (JSON array stored as text)
    images: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # PENDING / APPROVED / REJECTED /
    # PICKUP_SCHEDULED / PICKED_UP /
    # RETURNED_TO_SELLER / COMPLETED
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING"
    )

    # REFUND / REPLACE / EXCHANGE / null
    resolution: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    # Return shipment (reverse delivery)
    return_shipment_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey("shipments.id"),
            nullable=True
        )
    )

    # Admin who reviewed
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    # Admin notes
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
    order: Mapped["Order"] = relationship()

    user: Mapped["User"] = relationship()

    return_shipment: Mapped["Shipment | None"] = (
        relationship()
    )