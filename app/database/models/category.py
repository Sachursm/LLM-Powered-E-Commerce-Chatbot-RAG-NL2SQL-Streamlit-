from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.product import Product

from app.database.database import Base

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key = True)

    name: Mapped[str] = mapped_column(
        String(50),
        unique = True,
        index = True
    )

    products: Mapped[list["Product"]] = relationship(
        back_populates = "category"
    )