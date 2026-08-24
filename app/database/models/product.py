from sqlalchemy import Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.category import Category

from app.database.database import Base

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key = True)

    source_product_id: Mapped[int]= mapped_column(
        unique=True,
        index=True
    )

    name: Mapped[str]= mapped_column(
        String(255)
    )

    description: Mapped[str]= mapped_column(
        Text
    )

    price: Mapped[float]= mapped_column(
        Float
    )

    stock: Mapped[int]= mapped_column(
        Integer,
        default=0
    )

    image_url: Mapped[str]= mapped_column(
        Text
    ) 

    rating: Mapped[float]= mapped_column(
        Float,
        nullable = True
    )

    ratings_count: Mapped[int]= mapped_column(
        Integer,
        nullable=True
    )

    category_id: Mapped[int]= mapped_column(
        ForeignKey("categories.id")
    )

    category: Mapped["Category"] = relationship(
        back_populates="products"
    )