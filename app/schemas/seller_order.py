from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SellerOrderItemDetail(BaseModel):
    id: int
    order_id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SellerOrderResponse(BaseModel):
    order_id: int
    customer_id: int
    order_status: str
    payment_status: str
    order_created_at: datetime
    items: list[SellerOrderItemDetail]

    model_config = ConfigDict(from_attributes=True)
