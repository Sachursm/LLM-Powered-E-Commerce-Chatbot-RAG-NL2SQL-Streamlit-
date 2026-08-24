from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.order_item import OrderItem

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key= True)

    user_id : Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    user: Mapped["User"] = relationship(
        back_populates = "orders"
    )

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates= "order"
    )