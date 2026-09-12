from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReviewCreate(BaseModel):
    rating: int
    review_text: str | None = None


class ReviewUpdate(BaseModel):
    rating: int | None = None
    review_text: str | None = None


class ReviewResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    order_item_id: int
    rating: int
    review_text: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )