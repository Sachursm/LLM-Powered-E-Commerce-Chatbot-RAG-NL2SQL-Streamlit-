from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db
from app.database.models.user import User

from app.schemas.seller import SellerCreate, SellerResponse
from app.schemas.auth import ResetPasswordRequest
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

import secrets
from datetime import datetime, timedelta, timezone

from app.database.models.otp import OTP
from app.services.email import send_otp_email
from app.core.rate_limit import limiter
from slowapi.util import get_remote_address

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
@limiter.limit("3/minute", key_func=get_remote_address)
async def register(
    request: Request,
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
@limiter.limit("5/minute", key_func=get_remote_address)
async def login(
    request: Request,
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
@limiter.limit("3/minute", key_func=get_remote_address)
async def register_seller(
    request: Request,
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


# =========================================================
# FORGOT PASSWORD — Send OTP
# =========================================================

@router.post("/forgot-password")
@limiter.limit("3/minute", key_func=get_remote_address)
async def forgot_password(
    request: Request,
    email: str,
    db: AsyncSession = Depends(get_db)
):

    try:

        # -------------------------------------------------
        # Find user by email
        # -------------------------------------------------

        stmt = select(User).where(
            User.email == email
        )

        result = await db.execute(stmt)

        user = result.scalar_one_or_none()

        if user is None:
            return {
                "message": "If this email exists, an OTP has been sent"
            }

        # -------------------------------------------------
        # Delete any existing OTPs for this email
        # -------------------------------------------------

        delete_stmt = select(OTP).where(
            OTP.email == email
        )

        delete_result = await db.execute(delete_stmt)

        existing_otps = delete_result.scalars().all()

        for old_otp in existing_otps:
            await db.delete(old_otp)

        # -------------------------------------------------
        # Generate 6-digit OTP
        # -------------------------------------------------

        otp_code = str(secrets.randbelow(900000) + 100000)

        # -------------------------------------------------
        # Store OTP with 10 minute expiry
        # -------------------------------------------------

        otp = OTP(
            email=email,
            otp_code=otp_code,
            expires_at=(
                datetime.now(timezone.utc) +
                timedelta(minutes=10)
            )
        )

        db.add(otp)

        await db.commit()

        # -------------------------------------------------
        # Send OTP via email
        # -------------------------------------------------

        email_sent = await send_otp_email(
            email, otp_code
        )

        if not email_sent:
            print("FORGOT PASSWORD OTP email could not be sent")

        return {
            "message": "If this email exists, an OTP has been sent"
        }

    except HTTPException:

        raise

    except Exception as e:

        await db.rollback()

        print(f"FORGOT PASSWORD ERROR: {e}")

        raise HTTPException(
            status_code=503,
            detail=(
                "Service temporarily unavailable"
            )
        )


# =========================================================
# RESEND OTP
# =========================================================

@router.post("/resend-otp")
async def resend_otp(
    email: str,
    db: AsyncSession = Depends(get_db)
):

    try:

        # -------------------------------------------------
        # Verify email exists
        # -------------------------------------------------

        user_stmt = select(User).where(
            User.email == email
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is None:
            return {
                "message": "If this email exists, an OTP has been sent"
            }

        # -------------------------------------------------
        # Delete old OTPs
        # -------------------------------------------------

        delete_stmt = select(OTP).where(
            OTP.email == email
        )

        delete_result = await db.execute(delete_stmt)

        existing_otps = delete_result.scalars().all()

        for old_otp in existing_otps:
            await db.delete(old_otp)

        # -------------------------------------------------
        # Generate new OTP
        # -------------------------------------------------

        otp_code = str(secrets.randbelow(900000) + 100000)

        otp = OTP(
            email=email,
            otp_code=otp_code,
            expires_at=(
                datetime.now(timezone.utc) +
                timedelta(minutes=10)
            )
        )

        db.add(otp)

        await db.commit()

        # -------------------------------------------------
        # Send OTP
        # -------------------------------------------------

        email_sent = await send_otp_email(
            email, otp_code
        )

        if not email_sent:
            print("RESEND OTP email could not be sent")

        return {
            "message": "If this email exists, an OTP has been sent"
        }

    except HTTPException:

        raise

    except Exception as e:

        await db.rollback()

        print(f"RESEND OTP ERROR: {e}")

        raise HTTPException(
            status_code=503,
            detail=(
                "Service temporarily unavailable"
            )
        )


# =========================================================
# RESET PASSWORD — Verify OTP + Set New Password
# =========================================================

@router.post("/reset-password")
@limiter.limit("5/minute", key_func=get_remote_address)
async def reset_password(
    request: Request,
    reset_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):

    try:

        # -------------------------------------------------
        # Find OTP
        # -------------------------------------------------

        otp_stmt = (
            select(OTP)
            .where(
                OTP.email == reset_data.email,
                OTP.otp_code == reset_data.otp
            )
        )

        otp_result = await db.execute(otp_stmt)

        otp = otp_result.scalar_one_or_none()

        if otp is None:

            raise HTTPException(
                status_code=400,
                detail="Invalid OTP"
            )

        # -------------------------------------------------
        # Check if OTP is expired
        # -------------------------------------------------

        if datetime.now(timezone.utc) > (
            otp.expires_at.replace(
                tzinfo=timezone.utc
            )
        ):

            await db.delete(otp)

            await db.commit()

            raise HTTPException(
                status_code=400,
                detail="OTP has expired"
            )

        # -------------------------------------------------
        # Find user
        # -------------------------------------------------

        user_stmt = select(User).where(
            User.email == reset_data.email
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is None:

            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # -------------------------------------------------
        # Update password
        # -------------------------------------------------

        user.password_hash = hash_password(
            reset_data.new_password
        )

        # -------------------------------------------------
        # Delete OTP
        # -------------------------------------------------

        await db.delete(otp)

        await db.commit()

        return {
            "message": "Password reset successful"
        }

    except HTTPException:

        raise

    except Exception as e:

        await db.rollback()

        print(f"RESET PASSWORD ERROR: {e}")

        raise HTTPException(
            status_code=503,
            detail=(
                "Service temporarily unavailable"
            )
        )
