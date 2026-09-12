from datetime import datetime

from sqlalchemy import (
    ForeignKey, String, DateTime, Boolean
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.user import User


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Who owns this address
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # Label like "Home", "Office", "Warehouse"
    label: Mapped[str] = mapped_column(
        String(50),
        default="Home"
    )

    # Recipient name
    full_name: Mapped[str] = mapped_column(
        String(100)
    )

    # Contact phone
    phone: Mapped[str] = mapped_column(
        String(20)
    )

    # Address fields
    address_line_1: Mapped[str] = mapped_column(
        String(255)
    )

    address_line_2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    city: Mapped[str] = mapped_column(
        String(100)
    )

    state: Mapped[str] = mapped_column(
        String(100)
    )

    pincode: Mapped[str] = mapped_column(
        String(10)
    )

    # One default address per user
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False
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
    user: Mapped["User"] = relationship(
        back_populates="addresses"
    )