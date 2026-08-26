from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database.dependencies import get_db
from app.database.models.user import User
from app.schemas.user import (
    UserResponse,
    UserUpdate,
    ChangePassword
)
from app.core.security import (
    get_current_user,
    verify_password,
    hash_password
)

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

@router.patch("/me", response_model=UserResponse)
def update_my_profile(
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        if not verify_password(
            user_data.current_password,
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect"
            )

        update_data = user_data.model_dump(
            exclude_unset=True,
            exclude={"current_password"}
        )

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        if "username" in update_data:
            existing_username = db.execute(
                select(User).where(
                    User.username == update_data["username"],
                    User.id != current_user.id
                )
            ).scalar_one_or_none()

            if existing_username is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Username already exists"
                )

        if "email" in update_data:
            existing_email = db.execute(
                select(User).where(
                    User.email == update_data["email"],
                    User.id != current_user.id
                )
            ).scalar_one_or_none()

            if existing_email is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Email already exists"
                )

        for field, value in update_data.items():
            setattr(current_user, field, value)

        db.commit()
        db.refresh(current_user)

        return current_user

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.patch("/me/password")
def change_password(
    password_data: ChangePassword,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Verify the current password
        if not verify_password(
            password_data.current_password,
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect"
            )

        # Prevent using the same password
        if verify_password(
            password_data.new_password,
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=400,
                detail="New password must be different from current password"
            )

        # Hash the new password
        current_user.password_hash = hash_password(
            password_data.new_password
        )

        db.commit()

        return {
            "message": "Password changed successfully"
        }

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )