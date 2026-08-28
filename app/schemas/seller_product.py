from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SellerProductResponse(BaseModel):
    id: int
    seller_id: int
    product_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)