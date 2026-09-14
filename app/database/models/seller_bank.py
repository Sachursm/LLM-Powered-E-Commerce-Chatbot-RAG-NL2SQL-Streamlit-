from datetime import datetime

from sqlalchemy import (
    ForeignKey, String, DateTime
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.user import User


class SellerBank(Base):
    __tablename__ = "seller_banks"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True
    )

    account_holder: Mapped[str] = mapped_column(
        String(100)
    )

    bank_name: Mapped[str] = mapped_column(
        String(100)
    )

    account_number: Mapped[str] = mapped_column(
        String(50)
    )

    ifsc_code: Mapped[str] = mapped_column(
        String(20)
    )

    # UPI ID (optional)
    upi_id: Mapped[str | None] = mapped_column(
        String(50),
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
    seller: Mapped["User"] = relationship()