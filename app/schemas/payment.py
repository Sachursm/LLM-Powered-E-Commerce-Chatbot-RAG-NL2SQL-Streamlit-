from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    user_id: int
    amount: float
    currency: str
    method: str | None = None
    gateway: str
    gateway_payment_id: str | None = None
    gateway_status: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )