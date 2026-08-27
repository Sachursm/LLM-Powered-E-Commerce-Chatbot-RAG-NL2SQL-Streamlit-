from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import require_admin
from app.database.dependencies import get_db
from app.database.models.user import User
from app.schemas.user import UserResponse, RoleUpdate


router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


@router.get("/users", response_model=list[UserResponse])
def get_users(
    role: Literal["USER", "SELLER", "ADMIN"] | None = Query(
        default=None
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    stmt = select(User)

    if role is not None:
        stmt = stmt.where(User.role == role)

    result = db.execute(stmt)

    users = result.scalars().all()

    return users

@router.patch("/users/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: int,
    role_data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:
        stmt = select(User).where(User.id == user_id)

        result = db.execute(stmt)

        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if role_data.role not in ["USER", "SELLER", "ADMIN"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid role"
            )

        user.role = role_data.role

        db.commit()
        db.refresh(user)

        return user

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )