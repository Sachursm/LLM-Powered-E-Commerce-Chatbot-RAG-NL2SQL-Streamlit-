from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeliveryAgentCreate(BaseModel):
    user_id: int
    hub_id: int
    name: str
    phone: str


class DeliveryAgentUpdate(BaseModel):
    hub_id: int | None = None
    name: str | None = None
    phone: str | None = None
    status: str | None = None


class DeliveryAgentResponse(BaseModel):
    id: int
    user_id: int
    hub_id: int
    name: str
    phone: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )

# ---------------------------------------------------------
# AGENT FAILS DELIVERY
# ---------------------------------------------------------

class DeliveryFailRequest(BaseModel):
    reason: str