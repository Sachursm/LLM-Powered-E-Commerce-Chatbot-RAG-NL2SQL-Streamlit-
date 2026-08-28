from pydantic import BaseModel, EmailStr
from datetime import datetime


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str

class UserUpdate(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    current_password: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str

class RoleUpdate(BaseModel):
    role: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class ReactivationRequestResponse(BaseModel):
    id: int
    user_id: int
    email: EmailStr
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: int | None = None