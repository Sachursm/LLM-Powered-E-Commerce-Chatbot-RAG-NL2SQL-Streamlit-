from fastapi import (
    APIRouter, Depends, HTTPException, status
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.delivery_hub import DeliveryHub
from app.database.models.hub_manager import HubManager

from app.schemas.delivery_hub import (
    DeliveryHubCreate,
    DeliveryHubUpdate,
    DeliveryHubResponse
)

from app.schemas.hub_manager import (
    HubManagerCreate,
    HubManagerResponse
)

from app.core.security import require_admin


router = APIRouter(
    prefix="/delivery/hubs",
    tags=["Delivery Hubs"]
)


# =========================================================
# HUB CRUD
# =========================================================

@router.post(
    "",
    response_model=DeliveryHubResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_hub(
    hub_data: DeliveryHubCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        hub = DeliveryHub(
            name=hub_data.name,
            address=hub_data.address,
            city=hub_data.city,
            state=hub_data.state,
            pincode=hub_data.pincode
        )

        db.add(hub)

        await db.commit()

        await db.refresh(hub)

        return hub

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


@router.get(
    "",
    response_model=list[DeliveryHubResponse]
)
async def get_hubs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(DeliveryHub)
            .order_by(DeliveryHub.created_at.desc())
        )

        result = await db.execute(stmt)

        return result.scalars().all()

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


@router.get(
    "/{hub_id}",
    response_model=DeliveryHubResponse
)
async def get_hub(
    hub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(DeliveryHub)
            .where(DeliveryHub.id == hub_id)
        )

        result = await db.execute(stmt)

        hub = result.scalar_one_or_none()

        if hub is None:

            raise HTTPException(
                status_code=404,
                detail="Hub not found"
            )

        return hub

    except HTTPException:

        raise

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


@router.patch(
    "/{hub_id}",
    response_model=DeliveryHubResponse
)
async def update_hub(
    hub_id: int,
    hub_data: DeliveryHubUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(DeliveryHub)
            .where(DeliveryHub.id == hub_id)
        )

        result = await db.execute(stmt)

        hub = result.scalar_one_or_none()

        if hub is None:

            raise HTTPException(
                status_code=404,
                detail="Hub not found"
            )

        update_data = hub_data.model_dump(
            exclude_unset=True
        )

        if not update_data:

            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        for field, value in update_data.items():
            setattr(hub, field, value)

        await db.commit()

        await db.refresh(hub)

        return hub

    except HTTPException:

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# HUB MANAGERS
# =========================================================

@router.post(
    "/{hub_id}/managers",
    response_model=HubManagerResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_hub_manager(
    hub_id: int,
    manager_data: HubManagerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        hub_stmt = (
            select(DeliveryHub)
            .where(DeliveryHub.id == hub_id)
        )

        hub_result = await db.execute(hub_stmt)

        hub = hub_result.scalar_one_or_none()

        if hub is None:

            raise HTTPException(
                status_code=404,
                detail="Hub not found"
            )

        user_stmt = (
            select(User)
            .where(User.id == manager_data.user_id)
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is None:

            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        existing_stmt = (
            select(HubManager)
            .where(
                HubManager.user_id == (
                    manager_data.user_id
                )
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        if existing_result.scalar_one_or_none():

            raise HTTPException(
                status_code=400,
                detail="User is already a hub manager"
            )

        manager = HubManager(
            user_id=manager_data.user_id,
            hub_id=hub_id
        )

        db.add(manager)

        user.role = "HUB_MANAGER"

        await db.commit()

        await db.refresh(manager)

        return manager

    except HTTPException:

        await db.rollback()

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


@router.get(
    "/{hub_id}/managers",
    response_model=list[HubManagerResponse]
)
async def get_hub_managers(
    hub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(HubManager)
            .where(HubManager.hub_id == hub_id)
        )

        result = await db.execute(stmt)

        return result.scalars().all()

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# REMOVE HUB MANAGER
# =========================================================

@router.delete(
    "/{hub_id}/managers/{manager_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def remove_hub_manager(
    hub_id: int,
    manager_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(HubManager)
            .where(
                HubManager.id == manager_id,
                HubManager.hub_id == hub_id
            )
        )

        result = await db.execute(stmt)

        manager = result.scalar_one_or_none()

        if manager is None:

            raise HTTPException(
                status_code=404,
                detail="Hub manager not found"
            )

        # -------------------------------------------------
        # Revert user role back to USER
        # -------------------------------------------------

        user_stmt = (
            select(User)
            .where(User.id == manager.user_id)
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is not None:

            user.role = "USER"

        await db.delete(manager)

        await db.commit()

    except HTTPException:

        await db.rollback()

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )