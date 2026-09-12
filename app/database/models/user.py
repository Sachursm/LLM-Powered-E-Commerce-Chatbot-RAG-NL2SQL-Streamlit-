from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.seller_product import SellerProduct
    from app.database.models.cart import Cart
    from app.database.models.cart_item import CartItem
    from app.database.models.payment import Payment
    from app.database.models.address import Address
    from app.database.models.delivery_agent import DeliveryAgent
    from app.database.models.hub_manager import HubManager






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

    cart: Mapped["Cart"] = relationship(
    back_populates="user",
    uselist=False,
    cascade="all, delete-orphan"
    )

    payments: Mapped[list["Payment"]] = relationship(
    back_populates="user",
    cascade="all, delete-orphan"
   )

    # Add relationship:
    addresses: Mapped[list["Address"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # Add relationship:
    delivery_agent: Mapped["DeliveryAgent | None"] = relationship(
        back_populates="user",
        uselist=False
    )

    # Add relationship:
    hub_manager: Mapped["HubManager | None"] = relationship(
        back_populates="user",
        uselist=False
    )

