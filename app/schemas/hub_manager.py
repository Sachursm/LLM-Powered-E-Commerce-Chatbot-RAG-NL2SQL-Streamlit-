from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HubManagerCreate(BaseModel):
    user_id: int
    hub_id: int


class HubManagerResponse(BaseModel):
    id: int
    user_id: int
    hub_id: int
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )