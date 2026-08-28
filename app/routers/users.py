from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from datetime import datetime

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
def update_my_profile(
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
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
    current_user: User = Depends(require_active_user)
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



@router.patch("/me/deactivate")
def deactivate_my_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        current_user.status = "INACTIVE"
        current_user.deactivated_at = datetime.utcnow()

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=current_user.id,
            action="USER_DEACTIVATED",
            old_value="ACTIVE",
            new_value="INACTIVE"
        )

        db.add(audit_log)

        db.commit()

        return {
            "message": "Account deactivated successfully"
        }

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.post("/me/reactivation-request")
def request_reactivation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # User must be inactive to request reactivation
        if current_user.status == "ACTIVE":
            raise HTTPException(
                status_code=400,
                detail="Your account is already active"
            )

        # Check for an existing pending request
        existing_request = db.execute(
            select(ReactivationRequest).where(
                ReactivationRequest.user_id == current_user.id,
                ReactivationRequest.status == "PENDING"
            )
        ).scalar_one_or_none()

        if existing_request is not None:
            raise HTTPException(
                status_code=409,
                detail="A reactivation request is already pending"
            )

        # Create reactivation request
        reactivation_request = ReactivationRequest(
            user_id=current_user.id,
            email=current_user.email,
            status="PENDING"
        )

        db.add(reactivation_request)
        db.flush()

        # Create audit log
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=current_user.id,
            action="USER_REACTIVATION_REQUESTED",
            old_value="INACTIVE",
            new_value="PENDING"
        )

        db.add(audit_log)

        db.commit()

        return {
            "message": "Reactivation request submitted successfully",
            "status": "PENDING"
        }

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


