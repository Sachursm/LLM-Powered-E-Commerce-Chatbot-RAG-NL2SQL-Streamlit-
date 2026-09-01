from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db
from app.database.models.user import User
from app.schemas.user import (
    UserResponse,
    UserUpdate,
    ChangePassword
)
from app.core.security import (
    require_active_user,
    verify_password,
    hash_password,
    get_current_user
)

from app.database.models.reactivation_request import ReactivationRequest
from app.database.models.audit_log import AuditLog


router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Verify the user's current password before allowing
        # changes to the profile.
        if not verify_password(
            user_data.current_password,
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect"
            )

        # Extract only the fields the user wants to update.
        # current_password is only used for verification.
        update_data = user_data.model_dump(
            exclude_unset=True,
            exclude={"current_password"}
        )

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        # Check that the new username is not already used
        # by another user.
        if "username" in update_data:
            existing_username = await db.execute(
                select(User).where(
                    User.username == update_data["username"],
                    User.id != current_user.id
                )
            )

            if existing_username.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Username already exists"
                )

        # Check that the new email is not already used
        # by another user.
        if "email" in update_data:
            existing_email = await db.execute(
                select(User).where(
                    User.email == update_data["email"],
                    User.id != current_user.id
                )
            )

            if existing_email.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Email already exists"
                )

        # Apply the requested profile changes.
        for field, value in update_data.items():
            setattr(current_user, field, value)

        await db.commit()
        await db.refresh(current_user)

        return current_user

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.patch("/me/password")
async def change_password(
    password_data: ChangePassword,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Verify the current password before changing it.
        if not verify_password(
            password_data.current_password,
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect"
            )

        # Prevent using the same password again.
        if verify_password(
            password_data.new_password,
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=400,
                detail="New password must be different from current password"
            )

        # Hash the new password before storing it.
        current_user.password_hash = hash_password(
            password_data.new_password
        )

        await db.commit()

        return {
            "message": "Password changed successfully"
        }

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.patch("/me/deactivate")
async def deactivate_my_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Mark the current user's account as inactive.
        current_user.status = "INACTIVE"
        current_user.deactivated_at = datetime.utcnow()

        # Record the account deactivation in the audit log.
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=current_user.id,
            action="USER_DEACTIVATED",
            old_value="ACTIVE",
            new_value="INACTIVE"
        )

        db.add(audit_log)

        await db.commit()

        return {
            "message": "Account deactivated successfully"
        }

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.post("/me/reactivation-request")
async def request_reactivation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Only an inactive user can request reactivation.
        if current_user.status == "ACTIVE":
            raise HTTPException(
                status_code=400,
                detail="Your account is already active"
            )

        # Check whether the user already has a pending request.
        existing_request = await db.execute(
            select(ReactivationRequest).where(
                ReactivationRequest.user_id == current_user.id,
                ReactivationRequest.status == "PENDING"
            )
        )

        if existing_request.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="A reactivation request is already pending"
            )

        # Create a new reactivation request.
        reactivation_request = ReactivationRequest(
            user_id=current_user.id,
            email=current_user.email,
            status="PENDING"
        )

        db.add(reactivation_request)

        # Flush so the reactivation request is persisted
        # before creating the audit record.
        await db.flush()

        # Record the request in the audit log.
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=current_user.id,
            action="USER_REACTIVATION_REQUESTED",
            old_value="INACTIVE",
            new_value="PENDING"
        )

        db.add(audit_log)

        await db.commit()

        return {
            "message": "Reactivation request submitted successfully",
            "status": "PENDING"
        }

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )