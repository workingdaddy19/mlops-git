from datetime import datetime

from pydantic import BaseModel, Field


class PermissionRequestCreate(BaseModel):
    feature: str
    reason: str | None = Field(default=None, max_length=500)


class PermissionRequestRead(BaseModel):
    id: int
    user_id: int
    username: str
    feature: str
    reason: str | None
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None

    class Config:
        from_attributes = True
