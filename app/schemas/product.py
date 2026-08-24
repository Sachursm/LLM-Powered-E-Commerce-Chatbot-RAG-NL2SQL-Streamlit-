from pydantic import BaseModel


class ProductResponse(BaseModel):
    id: int
    source_product_id: int
    name: str
    description: str
    price: float
    stock: int
    image_url: str
    rating: float | None
    ratings_count: int | None
    category_id: int



class ProductCreate(BaseModel):
    source_product_id: int
    name: str
    description: str
    price: float
    stock: int
    image_url: str
    category_id: int