from fastapi import APIRouter, Depends

from app.core.security import (
    get_current_user,
    require_admin
)
from app.database.models.user import User

router = APIRouter(
    prefix="/test-auth",
    tags=["Authentication Test"]
)


@router.get("/me")
def get_me(
    current_user: User = Depends(get_current_user)
):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role
    }

@router.get("/admin")
def admin_test(
    current_user: User = Depends(require_admin)
):
    return {
        "message": "Welcome admin",
        "username": current_user.username,
        "role": current_user.role
    }