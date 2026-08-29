from pydantic import BaseModel


class ProductResponse(BaseModel):
    id: int
    source_product_id: int | None
    name: str
    description: str
    price: float
    stock: int
    image_url: str
    rating: float | None
    ratings_count: int | None
    category_id: int
    seller_id: int


class ProductCreate(BaseModel):
    source_product_id: int | None = None
    name: str
    description: str
    price: float
    stock: int
    image_url: str
    category: str
    seller_id: int

class ProductUpdate(BaseModel):
    source_product_id: int | None = None
    name: str | None = None
    description: str | None = None
    price: float | None = None
    stock: int | None = None
    image_url: str | None = None
    category: str | None = None