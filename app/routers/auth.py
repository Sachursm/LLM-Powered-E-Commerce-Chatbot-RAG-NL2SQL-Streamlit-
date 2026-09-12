from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db
from app.database.models.user import User

from app.schemas.seller import SellerCreate, SellerResponse
from app.schemas.user import (
    UserCreate,
    UserResponse,
    TokenResponse
)

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    try:
        # Check whether username already exists
        username_stmt = select(User).where(
            User.username == user_data.username
        )

        result = await db.execute(username_stmt)

        existing_username = result.scalar_one_or_none()

        if existing_username is not None:
            raise HTTPException(
                status_code=409,
                detail="Username already exists"
            )

        # Check whether email already exists
        email_stmt = select(User).where(
            User.email == user_data.email
        )

        result = await db.execute(email_stmt)

        existing_email = result.scalar_one_or_none()

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
            role="USER"
        )

        db.add(user)

        await db.commit()
        await db.refresh(user)

        return user

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.post(
    "/login",
    response_model=TokenResponse
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    try:
        stmt = select(User).where(
            User.username == form_data.username
        )

        result = await db.execute(stmt)

        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        if not verify_password(
            form_data.password,
            user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        access_token = create_access_token(
            user_id=user.id,
            role=user.role
        )

        return {
            "access_token": access_token,
            "token_type": "bearer"
        }

    except HTTPException:

        raise

    except Exception as e:

        print(f"LOGIN ERROR: {type(e).__name__}: {e}")

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.post(
    "/register-seller",
    response_model=SellerResponse,
    status_code=status.HTTP_201_CREATED
)
async def register_seller(
    seller_data: SellerCreate,
    db: AsyncSession = Depends(get_db)
):
    try:
        # Check username
        result = await db.execute(
            select(User).where(
                User.username == seller_data.username
            )
        )

        existing_username = result.scalar_one_or_none()

        if existing_username is not None:
            raise HTTPException(
                status_code=409,
                detail="Username already exists"
            )

        # Check email
        result = await db.execute(
            select(User).where(
                User.email == seller_data.email
            )
        )

        existing_email = result.scalar_one_or_none()

        if existing_email is not None:
            raise HTTPException(
                status_code=409,
                detail="Email already exists"
            )

        # Create seller
        seller = User(
            username=seller_data.username,
            email=seller_data.email,
            password_hash=hash_password(seller_data.password),
            role="SELLER",
            status="ACTIVE"
        )

        db.add(seller)

        await db.commit()
        await db.refresh(seller)

        return seller

    except SQLAlchemyError as e:
        await db.rollback()

        print("DATABASE ERROR:", e)

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )