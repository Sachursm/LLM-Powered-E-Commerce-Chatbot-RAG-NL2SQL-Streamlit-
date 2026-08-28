from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.seller_product import SellerProduct


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True
    )

    email: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        String(255)
    )

    role: Mapped[str] = mapped_column(
        String(20),
        default="USER",
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    orders: Mapped[list["Order"]] = relationship(
        back_populates="user"
    )


    seller_products: Mapped[list["SellerProduct"]] = relationship(
    back_populates="seller",
    cascade="all, delete-orphan"
    )