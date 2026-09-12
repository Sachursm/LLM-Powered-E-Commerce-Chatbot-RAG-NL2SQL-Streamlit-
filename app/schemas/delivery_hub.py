from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeliveryHubCreate(BaseModel):
    name: str
    address: str
    city: str
    state: str
    pincode: str


class DeliveryHubUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    status: str | None = None


class DeliveryHubResponse(BaseModel):
    id: int
    name: str
    address: str
    city: str
    state: str
    pincode: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )