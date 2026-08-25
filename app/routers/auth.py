from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database.dependencies import get_db
from app.database.models.user import User
from app.schemas.user import UserCreate, UserResponse


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    try:
        # Check whether username already exists
        username_stmt = select(User).where(
            User.username == user_data.username
        )

        existing_username = db.execute(
            username_stmt
        ).scalar_one_or_none()

        if existing_username is not None:
            raise HTTPException(
                status_code=409,
                detail="Username already exists"
            )

        # Check whether email already exists
        email_stmt = select(User).where(
            User.email == user_data.email
        )

        existing_email = db.execute(
            email_stmt
        ).scalar_one_or_none()

        if existing_email is not None:
            raise HTTPException(
                status_code=409,
                detail="Email already exists"
            )

        # Hash password before storing it
        password_hash = hash_password(user_data.password)

        user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=password_hash,
            role="user"
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )