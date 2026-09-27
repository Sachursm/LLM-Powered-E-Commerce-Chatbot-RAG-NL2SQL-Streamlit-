from typing import Literal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.core.rate_limit import limiter, get_user_key
from app.database.dependencies import get_db
from app.database.models.user import User
from app.database.models.audit_log import AuditLog
from app.schemas.user import UserResponse, RoleUpdate
from app.database.models.reactivation_request import ReactivationRequest
from app.schemas.user import ReactivationRequestResponse


router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


# =========================================================
# GET USERS
# =========================================================

@router.get(
    "/users",
    response_model=list[UserResponse]
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_users(
    request: Request,
    role: Literal["USER", "SELLER", "ADMIN"] | None = Query(
        default=None
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        stmt = select(User)

        if role is not None:
            stmt = stmt.where(
                User.role == role
            )

        result = await db.execute(stmt)

        users = result.scalars().all()

        return users

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# UPDATE USER ROLE
# =========================================================

@router.patch(
    "/users/{user_id}/role",
    response_model=UserResponse
)
@limiter.limit("20/minute", key_func=get_user_key)
async def update_user_role(
    request: Request,
    user_id: int,
    role_data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        stmt = select(User).where(
            User.id == user_id
        )

        result = await db.execute(stmt)

        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if role_data.role not in [
            "USER",
            "SELLER",
            "ADMIN"
        ]:
            raise HTTPException(
                status_code=400,
                detail="Invalid role"
            )

        # Prevent removing the last active admin
        if (
            user.role == "ADMIN"
            and user.status == "ACTIVE"
            and role_data.role != "ADMIN"
        ):

            active_admin_result = await db.execute(
                select(User).where(
                    User.role == "ADMIN",
                    User.status == "ACTIVE"
                )
            )

            active_admin_count = (
                active_admin_result.scalars().all()
            )

            if len(active_admin_count) == 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last active admin"
                )

        old_role = user.role

        user.role = role_data.role
        user.updated_at = datetime.utcnow()

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=user.id,
            action="ROLE_CHANGED",
            old_value=old_role,
            new_value=role_data.role
        )

        db.add(audit_log)

        await db.commit()

        await db.refresh(user)

        return user

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# DEACTIVATE USER
# =========================================================

@router.patch(
    "/users/{user_id}/deactivate",
    response_model=UserResponse
)
@limiter.limit("20/minute", key_func=get_user_key)
async def deactivate_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        stmt = select(User).where(
            User.id == user_id
        )

        result = await db.execute(stmt)

        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.status == "INACTIVE":
            raise HTTPException(
                status_code=400,
                detail="User is already inactive"
            )

        # Prevent deactivating the last active admin
        if user.role == "ADMIN":

            active_admin_result = await db.execute(
                select(User).where(
                    User.role == "ADMIN",
                    User.status == "ACTIVE"
                )
            )

            active_admin_count = (
                active_admin_result.scalars().all()
            )

            if len(active_admin_count) == 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot deactivate the last active admin"
                )

        old_status = user.status

        user.status = "INACTIVE"
        user.deactivated_at = datetime.utcnow()
        user.updated_at = datetime.utcnow()

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=user.id,
            action="USER_DEACTIVATED",
            old_value=old_status,
            new_value="INACTIVE"
        )

        db.add(audit_log)

        await db.commit()

        await db.refresh(user)

        return user

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# ACTIVATE USER
# =========================================================

@router.patch(
    "/users/{user_id}/activate",
    response_model=UserResponse
)
@limiter.limit("20/minute", key_func=get_user_key)
async def activate_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        stmt = select(User).where(
            User.id == user_id
        )

        result = await db.execute(stmt)

        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if user.status == "ACTIVE":
            raise HTTPException(
                status_code=400,
                detail="User is already active"
            )

        old_status = user.status

        user.status = "ACTIVE"
        user.deactivated_at = None
        user.updated_at = datetime.utcnow()

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=user.id,
            action="USER_ACTIVATED",
            old_value=old_status,
            new_value="ACTIVE"
        )

        db.add(audit_log)

        await db.commit()

        await db.refresh(user)

        return user

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# GET REACTIVATION REQUESTS
# =========================================================

@router.get(
    "/reactivation-requests",
    response_model=list[ReactivationRequestResponse]
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_reactivation_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        stmt = (
            select(ReactivationRequest)
            .where(
                ReactivationRequest.status == "PENDING"
            )
            .order_by(
                ReactivationRequest.created_at
            )
        )

        result = await db.execute(stmt)

        requests = result.scalars().all()

        return requests

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# APPROVE REACTIVATION REQUEST
# =========================================================

@router.post(
    "/reactivation-requests/{request_id}/approve"
)
@limiter.limit("20/minute", key_func=get_user_key)
async def approve_reactivation_request(
    request: Request,
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        # Find request
        stmt = select(ReactivationRequest).where(
            ReactivationRequest.id == request_id
        )

        result = await db.execute(stmt)

        request = result.scalar_one_or_none()

        if request is None:
            raise HTTPException(
                status_code=404,
                detail="Reactivation request not found"
            )

        # Make sure it is still pending
        if request.status != "PENDING":
            raise HTTPException(
                status_code=409,
                detail="Reactivation request has already been reviewed"
            )

        # Find user
        user_stmt = select(User).where(
            User.id == request.user_id
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Reactivate user
        user.status = "ACTIVE"
        user.deactivated_at = None
        user.updated_at = datetime.utcnow()

        # Update request
        request.status = "APPROVED"
        request.reviewed_at = datetime.utcnow()
        request.reviewed_by = current_user.id

        # Audit log
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=user.id,
            action="USER_REACTIVATED",
            old_value="INACTIVE",
            new_value="ACTIVE"
        )

        db.add(audit_log)

        # One transaction
        await db.commit()

        return {
            "message": "User account reactivated successfully"
        }

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# REJECT REACTIVATION REQUEST
# =========================================================

@router.post(
    "/reactivation-requests/{request_id}/reject"
)
@limiter.limit("20/minute", key_func=get_user_key)
async def reject_reactivation_request(
    request: Request,
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        # Find request
        stmt = select(ReactivationRequest).where(
            ReactivationRequest.id == request_id
        )

        result = await db.execute(stmt)

        request = result.scalar_one_or_none()

        if request is None:
            raise HTTPException(
                status_code=404,
                detail="Reactivation request not found"
            )

        # Make sure request is still pending
        if request.status != "PENDING":
            raise HTTPException(
                status_code=409,
                detail="Reactivation request has already been reviewed"
            )

        # Find user
        user_stmt = select(User).where(
            User.id == request.user_id
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Reject request
        request.status = "REJECTED"
        request.reviewed_at = datetime.utcnow()
        request.reviewed_by = current_user.id

        # Audit log
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="USER",
            target_id=user.id,
            action="USER_REACTIVATION_REJECTED",
            old_value="INACTIVE",
            new_value="INACTIVE"
        )

        db.add(audit_log)

        await db.commit()

        return {
            "message": "Reactivation request rejected successfully"
        }

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )