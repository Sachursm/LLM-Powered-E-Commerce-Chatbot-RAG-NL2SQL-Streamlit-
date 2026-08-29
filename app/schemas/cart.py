from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.cart_item import CartItemResponse



class CartResponse(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    items: list[CartItemResponse]

    model_config = ConfigDict(from_attributes=True)