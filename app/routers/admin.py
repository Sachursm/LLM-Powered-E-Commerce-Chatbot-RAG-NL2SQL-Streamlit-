from typing import Literal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import require_admin
from app.database.dependencies import get_db
from app.database.models.user import User
from app.database.models.audit_log import AuditLog
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

        if (
            user.role == "ADMIN"
            and user.status == "ACTIVE"
            and role_data.role != "ADMIN"
        ):
            active_admin_count = db.execute(
                select(User).where(
                    User.role == "ADMIN",
                    User.status == "ACTIVE"
                )
            ).scalars().all()

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

        db.commit()
        db.refresh(user)

        return user

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.patch(
    "/users/{user_id}/deactivate",
    response_model=UserResponse
)
def deactivate_user(
    user_id: int,
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

        if user.status == "INACTIVE":
            raise HTTPException(
                status_code=400,
                detail="User is already inactive"
            )

        if user.role == "ADMIN":
            active_admin_count = db.execute(
                select(User).where(
                    User.role == "ADMIN",
                    User.status == "ACTIVE"
                )
            ).scalars().all()

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

        db.commit()
        db.refresh(user)

        return user

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.patch(
    "/users/{user_id}/activate",
    response_model=UserResponse
)
def activate_user(
    user_id: int,
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

        db.commit()
        db.refresh(user)

        return user

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )