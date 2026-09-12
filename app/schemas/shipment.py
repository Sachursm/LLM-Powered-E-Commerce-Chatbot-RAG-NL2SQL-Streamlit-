from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ShipmentTrackingResponse(BaseModel):
    id: int
    shipment_id: int
    status: str
    description: str
    created_by: int | None = None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class ShipmentResponse(BaseModel):
    id: int
    order_id: int
    seller_id: int
    customer_id: int
    status: str
    shipping_address_id: int | None = None
    shipped_by: int | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    tracking_events: list[ShipmentTrackingResponse] = []
    current_hub_id: int | None = None
    assigned_agent_id: int | None = None

    model_config = ConfigDict(
        from_attributes=True
    )

# ---------------------------------------------------------
# SHIP-OUT (Shipment leaves hub)
# ---------------------------------------------------------
class ShipOutRequest(BaseModel):
    destination_hub_id: int