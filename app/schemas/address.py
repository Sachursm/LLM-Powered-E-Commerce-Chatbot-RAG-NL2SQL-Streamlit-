from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AddressCreate(BaseModel):
    label: str = "Home"
    full_name: str
    phone: str
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    pincode: str
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = None
    full_name: str | None = None
    phone: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    is_default: bool | None = None


class AddressResponse(BaseModel):
    id: int
    user_id: int
    label: str
    full_name: str
    phone: str
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    pincode: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )