from fastapi import (
    APIRouter, Depends, HTTPException, Query, status
)

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.seller_bank import SellerBank
from app.database.models.seller_payout import (
    SellerPayout
)

from app.schemas.seller_payout import (
    SellerBankCreate,
    SellerBankUpdate,
    SellerBankResponse,
    SellerPayoutResponse
)

from app.core.security import require_admin_or_seller
from datetime import date, datetime, time

from app.schemas.pagination import PaginatedResponse


router = APIRouter(
    tags=["Seller Payouts"]
)


# =========================================================
# SELLER BANK DETAILS
# =========================================================

@router.post(
    "/seller/bank",
    response_model=SellerBankResponse,
    status_code=status.HTTP_201_CREATED
)
async def add_bank_details(
    bank_data: SellerBankCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        existing_stmt = (
            select(SellerBank)
            .where(
                SellerBank.seller_id == current_user.id
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        if existing_result.scalar_one_or_none():

            raise HTTPException(
                status_code=400,
                detail=(
                    "Bank details already exist. "
                    "Use PATCH to update"
                )
            )

        bank = SellerBank(
            seller_id=current_user.id,
            account_holder=bank_data.account_holder,
            bank_name=bank_data.bank_name,
            account_number=bank_data.account_number,
            ifsc_code=bank_data.ifsc_code,
            upi_id=bank_data.upi_id
        )

        db.add(bank)

        await db.commit()

        await db.refresh(bank)

        return bank

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
    "/seller/bank",
    response_model=SellerBankResponse
)
async def get_bank_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        stmt = (
            select(SellerBank)
            .where(
                SellerBank.seller_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        bank = result.scalar_one_or_none()

        if bank is None:

            raise HTTPException(
                status_code=404,
                detail="Bank details not found"
            )

        return bank

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
    "/seller/bank",
    response_model=SellerBankResponse
)
async def update_bank_details(
    bank_data: SellerBankUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        stmt = (
            select(SellerBank)
            .where(
                SellerBank.seller_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        bank = result.scalar_one_or_none()

        if bank is None:

            raise HTTPException(
                status_code=404,
                detail="Bank details not found"
            )

        update_data = bank_data.model_dump(
            exclude_unset=True
        )

        if not update_data:

            raise HTTPException(
                status_code=400,
                detail="No fields provided"
            )

        for field, value in update_data.items():
            setattr(bank, field, value)

        await db.commit()

        await db.refresh(bank)

        return bank

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


# =========================================================
# SELLER: VIEW MY PAYOUTS
# =========================================================
@router.get(
    "/seller/payouts",
    response_model=PaginatedResponse[SellerPayoutResponse]
)
async def get_my_payouts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller),
    skip: int = 0,
    limit: int = 20,
    from_date: date | None = None,
    to_date: date | None = None,
    status_filter: str | None = Query(
        None, alias="status"
    )
):

    try:

        stmt = (
            select(SellerPayout)
            .where(
                SellerPayout.seller_id == current_user.id
            )
        )

        count_stmt = (
            select(func.count(SellerPayout.id))
            .where(
                SellerPayout.seller_id == current_user.id
            )
        )

        if from_date is not None:

            from_datetime = datetime.combine(
                from_date, time.min
            )

            stmt = stmt.where(
                SellerPayout.created_at >= from_datetime
            )

            count_stmt = count_stmt.where(
                SellerPayout.created_at >= from_datetime
            )

        if to_date is not None:

            to_datetime = datetime.combine(
                to_date, time.max
            )

            stmt = stmt.where(
                SellerPayout.created_at <= to_datetime
            )

            count_stmt = count_stmt.where(
                SellerPayout.created_at <= to_datetime
            )

        if status_filter is not None:

            stmt = stmt.where(
                SellerPayout.status == (
                    status_filter.upper()
                )
            )

            count_stmt = count_stmt.where(
                SellerPayout.status == (
                    status_filter.upper()
                )
            )

        total_result = await db.execute(count_stmt)

        total = total_result.scalar()

        stmt = (
            stmt
            .order_by(SellerPayout.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(stmt)

        return {
            "items": result.scalars().all(),
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total
        }

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )

# =========================================================
# SELLER: PAYOUT SUMMARY
# =========================================================

@router.get("/seller/payouts/summary")
async def get_payout_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        total_stmt = (
            select(
                func.sum(SellerPayout.payout_amount)
            )
            .where(
                SellerPayout.seller_id == current_user.id,
                SellerPayout.status == "PAID"
            )
        )

        total_result = await db.execute(total_stmt)

        total_paid = total_result.scalar() or 0

        pending_stmt = (
            select(
                func.sum(SellerPayout.payout_amount)
            )
            .where(
                SellerPayout.seller_id == current_user.id,
                SellerPayout.status.in_(
                    ["PENDING", "ELIGIBLE"]
                )
            )
        )

        pending_result = await db.execute(
            pending_stmt
        )

        total_pending = pending_result.scalar() or 0

        hold_stmt = (
            select(
                func.sum(SellerPayout.payout_amount)
            )
            .where(
                SellerPayout.seller_id == current_user.id,
                SellerPayout.status == "ON_HOLD"
            )
        )

        hold_result = await db.execute(hold_stmt)

        total_on_hold = hold_result.scalar() or 0

        commission_stmt = (
            select(
                func.sum(
                    SellerPayout.commission_amount
                )
            )
            .where(
                SellerPayout.seller_id == current_user.id
            )
        )

        commission_result = await db.execute(
            commission_stmt
        )

        total_commission = (
            commission_result.scalar() or 0
        )

        return {
            "total_paid": total_paid,
            "total_pending": total_pending,
            "total_on_hold": total_on_hold,
            "total_commission": total_commission
        }

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )