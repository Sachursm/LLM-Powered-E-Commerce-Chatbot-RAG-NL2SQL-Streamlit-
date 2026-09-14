from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SellerBankCreate(BaseModel):
    account_holder: str
    bank_name: str
    account_number: str
    ifsc_code: str
    upi_id: str | None = None


class SellerBankUpdate(BaseModel):
    account_holder: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    upi_id: str | None = None


class SellerBankResponse(BaseModel):
    id: int
    seller_id: int
    account_holder: str
    bank_name: str
    account_number: str
    ifsc_code: str
    upi_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class CommissionUpdate(BaseModel):
    rate: float


class CommissionResponse(BaseModel):
    id: int
    seller_id: int
    rate: float
    set_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class SellerPayoutResponse(BaseModel):
    id: int
    seller_id: int
    order_id: int
    order_item_id: int
    product_id: int
    sale_amount: float
    commission_rate: float
    commission_amount: float
    payout_amount: float
    status: str
    eligible_at: datetime | None = None
    paid_at: datetime | None = None
    transaction_ref: str | None = None
    admin_notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class PayoutProcess(BaseModel):
    transaction_ref: str
    admin_notes: str | None = None


class PayoutHold(BaseModel):
    admin_notes: str