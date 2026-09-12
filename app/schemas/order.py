from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreateOrderRequest(BaseModel):
    shipping_address_id: int


class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    product_id: int
    owner_id: int
    quantity: int
    unit_price: float
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: str
    payment_status: str
    shipping_address_id: int | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

    model_config = ConfigDict(
        from_attributes=True
    )