from pydantic import BaseModel, EmailStr


class SellerCreate(BaseModel):

    username: str

    email: EmailStr

    password: str


class SellerResponse(BaseModel):

    id: int

    username: str

    email: EmailStr

    role: str