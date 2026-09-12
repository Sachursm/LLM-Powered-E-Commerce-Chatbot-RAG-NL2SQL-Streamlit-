from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReturnRequestCreate(BaseModel):
    type: str
    reason: str
    description: str | None = None
    images: list[str] | None = None


class ReturnApprove(BaseModel):
    resolution: str
    destination_hub_id: int
    admin_notes: str | None = None


class ReturnReject(BaseModel):
    admin_notes: str


class ReturnRequestResponse(BaseModel):
    id: int
    order_id: int
    order_item_id: int
    product_id: int
    user_id: int
    type: str
    reason: str
    description: str | None = None
    images: str | None = None
    status: str
    resolution: str | None = None
    return_shipment_id: int | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    admin_notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )