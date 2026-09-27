from pydantic import BaseModel


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str
