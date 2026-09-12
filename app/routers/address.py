from fastapi import (
    APIRouter, Depends, HTTPException, status
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.address import Address

from app.schemas.address import (
    AddressCreate,
    AddressUpdate,
    AddressResponse
)

from app.core.security import require_active_user


router = APIRouter(
    prefix="/addresses",
    tags=["Addresses"]
)


# =========================================================
# CREATE ADDRESS
# =========================================================

@router.post(
    "",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_address(
    address_data: AddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        # -------------------------------------------------
        # If this is set as default, unset other defaults
        # -------------------------------------------------

        if address_data.is_default:

            existing_stmt = (
                select(Address)
                .where(
                    Address.user_id == current_user.id,
                    Address.is_default == True
                )
            )

            existing_result = await db.execute(
                existing_stmt
            )

            existing_defaults = (
                existing_result.scalars().all()
            )

            for addr in existing_defaults:
                addr.is_default = False

        # -------------------------------------------------
        # Create address
        # -------------------------------------------------

        address = Address(
            user_id=current_user.id,
            label=address_data.label,
            full_name=address_data.full_name,
            phone=address_data.phone,
            address_line_1=address_data.address_line_1,
            address_line_2=address_data.address_line_2,
            city=address_data.city,
            state=address_data.state,
            pincode=address_data.pincode,
            is_default=address_data.is_default
        )

        db.add(address)

        # -------------------------------------------------
        # If this is the user's first address,
        # make it default automatically
        # -------------------------------------------------

        count_stmt = (
            select(Address)
            .where(
                Address.user_id == current_user.id
            )
        )

        count_result = await db.execute(count_stmt)

        if not count_result.scalars().all():
            address.is_default = True

        await db.commit()

        await db.refresh(address)

        return address

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
# GET MY ADDRESSES
# =========================================================

@router.get(
    "",
    response_model=list[AddressResponse]
)
async def get_my_addresses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Address)
            .where(
                Address.user_id == current_user.id
            )
            .order_by(
                Address.is_default.desc(),
                Address.created_at.desc()
            )
        )

        result = await db.execute(stmt)

        addresses = result.scalars().all()

        return addresses

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# GET SINGLE ADDRESS
# =========================================================

@router.get(
    "/{address_id}",
    response_model=AddressResponse
)
async def get_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Address)
            .where(
                Address.id == address_id,
                Address.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        address = result.scalar_one_or_none()

        if address is None:

            raise HTTPException(
                status_code=404,
                detail="Address not found"
            )

        return address

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


# =========================================================
# UPDATE ADDRESS
# =========================================================

@router.patch(
    "/{address_id}",
    response_model=AddressResponse
)
async def update_address(
    address_id: int,
    address_data: AddressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Address)
            .where(
                Address.id == address_id,
                Address.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        address = result.scalar_one_or_none()

        if address is None:

            raise HTTPException(
                status_code=404,
                detail="Address not found"
            )

        update_data = address_data.model_dump(
            exclude_unset=True
        )

        if not update_data:

            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        # -------------------------------------------------
        # Handle default toggle
        # -------------------------------------------------

        if update_data.get("is_default") is True:

            existing_stmt = (
                select(Address)
                .where(
                    Address.user_id == current_user.id,
                    Address.is_default == True,
                    Address.id != address_id
                )
            )

            existing_result = await db.execute(
                existing_stmt
            )

            for addr in existing_result.scalars().all():
                addr.is_default = False

        for field, value in update_data.items():
            setattr(address, field, value)

        await db.commit()

        await db.refresh(address)

        return address

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
# DELETE ADDRESS
# =========================================================

@router.delete(
    "/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Address)
            .where(
                Address.id == address_id,
                Address.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        address = result.scalar_one_or_none()

        if address is None:

            raise HTTPException(
                status_code=404,
                detail="Address not found"
            )

        was_default = address.is_default

        await db.delete(address)

        # -------------------------------------------------
        # If deleted address was default, make the
        # most recent remaining address the new default
        # -------------------------------------------------

        if was_default:

            next_stmt = (
                select(Address)
                .where(
                    Address.user_id == current_user.id
                )
                .order_by(
                    Address.created_at.desc()
                )
                .limit(1)
            )

            next_result = await db.execute(next_stmt)

            next_address = (
                next_result.scalar_one_or_none()
            )

            if next_address is not None:
                next_address.is_default = True

        await db.commit()

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