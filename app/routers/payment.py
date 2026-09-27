import hmac
import hashlib
import json

from fastapi import (
    APIRouter, Depends, HTTPException,
    Request, status
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import razorpay

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.order import Order
from app.database.models.payment import Payment
from app.database.models.order_item import (
    OrderItem
)
from app.database.models.seller_payout import (
    SellerPayout,
    SellerCommission
)


from app.schemas.payment import PaymentResponse

from app.core.security import require_active_user
from app.core.rate_limit import limiter, get_user_key
from app.core.config import settings


# ---------------------------------------------------------
# Razorpay client (test mode)
# ---------------------------------------------------------

razorpay_client = razorpay.Client(
    auth=(
        settings.RAZORPAY_KEY_ID,
        settings.RAZORPAY_KEY_SECRET
    )
)


router = APIRouter(
    prefix="/payments",
    tags=["Payments"]
)


# =========================================================
# CREATE RAZORPAY ORDER
# =========================================================

@router.post(
    "/{order_id}/checkout",
    status_code=status.HTTP_201_CREATED
)
@limiter.limit("3/minute", key_func=get_user_key)
async def create_checkout(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        # -------------------------------------------------
        # Find the order
        # -------------------------------------------------

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items)
            )
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        order = result.scalar_one_or_none()

        if order is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        # -------------------------------------------------
        # Check if already paid
        # -------------------------------------------------

        if order.payment_status == "PAID":

            raise HTTPException(
                status_code=400,
                detail="Order is already paid"
            )

        # -------------------------------------------------
        # Check if order is cancelled
        # -------------------------------------------------

        if order.status == "CANCELLED":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot pay for a "
                    "cancelled order"
                )
            )

        # -------------------------------------------------
        # Calculate total amount
        # -------------------------------------------------

        total_amount = sum(
            item.unit_price * item.quantity
            for item in order.items
        )

        amount_in_paise = int(total_amount * 100)

        # -------------------------------------------------
        # Create Razorpay order
        # -------------------------------------------------

        razorpay_order = razorpay_client.order.create({
            "amount": amount_in_paise,
            "currency": "INR",
            "notes": {
                "order_id": str(order.id),
                "user_id": str(current_user.id)
            }
        })

        # -------------------------------------------------
        # Create a payment link
        # -------------------------------------------------

        payment_link = razorpay_client.payment_link.create({
            "amount": amount_in_paise,
            "currency": "INR",
            "description": (
                f"Payment for Order #{order.id}"
            ),
            "notes": {
                "order_id": str(order.id),
                "user_id": str(current_user.id)
            },
            "callback_url": (
                "https://renovator-hardware-declared"
                ".ngrok-free.dev"
                "/payments/verify"
            ),
            "callback_method": "get"
        })

        # -------------------------------------------------
        # Create Payment record
        # -------------------------------------------------

        payment = Payment(
            order_id=order.id,
            user_id=current_user.id,
            amount=total_amount,
            currency="INR",
            gateway="razorpay",
            gateway_payment_id=razorpay_order["id"],
            gateway_status="created",
            status="PENDING"
        )

        db.add(payment)

        await db.commit()

        # -------------------------------------------------
        # Return payment details
        # -------------------------------------------------

        return {
            "razorpay_order_id": razorpay_order["id"],
            "amount": total_amount,
            "currency": "INR",
            "payment_link": payment_link["short_url"],
            "key_id": settings.RAZORPAY_KEY_ID
        }

    except HTTPException:

        await db.rollback()

        raise

    except Exception as e:

        await db.rollback()
        print(f"PAYMENT ERROR: {e}")

        raise HTTPException(
            status_code=502,
            detail="Payment processing failed. Please try again."
        )


# =========================================================
# RAZORPAY WEBHOOK
# =========================================================

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK
)
@limiter.exempt
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):

    try:

        payload = await request.body()

        signature = request.headers.get(
            "X-Razorpay-Signature"
        )

        # -------------------------------------------------
        # Verify webhook signature
        # -------------------------------------------------

        if signature is None:

            raise HTTPException(
                status_code=400,
                detail="Missing signature"
            )

        expected_signature = hmac.new(
            key=settings.RAZORPAY_WEBHOOK_SECRET.encode(),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            expected_signature, signature
        ):

            raise HTTPException(
                status_code=400,
                detail="Invalid signature"
            )

        # -------------------------------------------------
        # Parse the event
        # -------------------------------------------------

        event = json.loads(payload)

        event_type = event.get("event")

        # -------------------------------------------------
        # payment.captured → SUCCESS
        # -------------------------------------------------

        if event_type == "payment.captured":

            payment_entity = (
                event["payload"]["payment"]["entity"]
            )

            razorpay_payment_id = (
                payment_entity.get("id")
            )

            method = payment_entity.get("method")

            # -----------------------------------------
            # Get our internal order_id from notes
            # -----------------------------------------

            notes = payment_entity.get("notes", {})

            internal_order_id = notes.get("order_id")

            if internal_order_id is None:

                return {"status": "ok"}

            # -----------------------------------------
            # Find the payment record by our order_id
            # -----------------------------------------

            payment_stmt = (
                select(Payment)
                .where(
                    Payment.order_id == int(
                        internal_order_id
                    )
                )
                .order_by(
                    Payment.created_at.desc()
                )
                .limit(1)
            )

            payment_result = await db.execute(
                payment_stmt
            )

            payment = (
                payment_result.scalar_one_or_none()
            )

            if payment is not None:

                payment.status = "SUCCESS"
                payment.gateway_status = "captured"
                payment.method = method
                payment.gateway_payment_id = (
                    razorpay_payment_id
                )

                # ---------------------------------
                # Update order payment status
                # ---------------------------------

                order_stmt = (
                    select(Order)
                    .where(
                        Order.id == payment.order_id
                    )
                )

                order_result = await db.execute(
                    order_stmt
                )

                order = (
                    order_result.scalar_one_or_none()
                )

                if order is not None:

                    order.payment_status = "PAID"
                    order.status = "CONFIRMED"

                    
                    items_stmt = (
                        select(OrderItem)
                        .where(
                            OrderItem.order_id == (
                                order.id
                            )
                        )
                    )

                    items_result = await db.execute(
                        items_stmt
                    )

                    order_items = (
                        items_result.scalars().all()
                    )

                    for item in order_items:

                        existing_payout_result = await db.execute(
                            select(SellerPayout.id)
                            .where(
                                SellerPayout.order_item_id == item.id
                            )
                            .limit(1)
                        )

                        if existing_payout_result.scalar_one_or_none() is not None:
                            continue

                        comm_stmt = (
                            select(SellerCommission)
                            .where(
                                SellerCommission.seller_id
                                == item.owner_id
                            )
                        )

                        comm_result = await db.execute(
                            comm_stmt
                        )

                        commission = (
                            comm_result
                            .scalar_one_or_none()
                        )

                        rate = (
                            commission.rate
                            if commission
                            else 0.15
                        )

                        sale_amount = (
                            item.unit_price *
                            item.quantity
                        )

                        commission_amount = (
                            sale_amount * rate
                        )

                        payout_amount = (
                            sale_amount -
                            commission_amount
                        )

                        payout = SellerPayout(
                            seller_id=item.owner_id,
                            order_id=order.id,
                            order_item_id=item.id,
                            product_id=item.product_id,
                            sale_amount=sale_amount,
                            commission_rate=rate,
                            commission_amount=round(
                                commission_amount, 2
                            ),
                            payout_amount=round(
                                payout_amount, 2
                            ),
                            status="PENDING"
                        )

                        db.add(payout)

                await db.commit()

        # -------------------------------------------------
        # payment.failed → FAILED
        # -------------------------------------------------

        elif event_type == "payment.failed":

            payment_entity = (
                event["payload"]["payment"]["entity"]
            )

            notes = payment_entity.get("notes", {})

            internal_order_id = notes.get("order_id")

            if internal_order_id is None:

                return {"status": "ok"}

            payment_stmt = (
                select(Payment)
                .where(
                    Payment.order_id == int(
                        internal_order_id
                    )
                )
                .order_by(
                    Payment.created_at.desc()
                )
                .limit(1)
            )

            payment_result = await db.execute(
                payment_stmt
            )

            payment = (
                payment_result.scalar_one_or_none()
            )

            if payment is not None:

                payment.status = "FAILED"
                payment.gateway_status = "failed"

                # ---------------------------------
                # Update order payment status
                # ---------------------------------

                order_stmt = (
                    select(Order)
                    .where(
                        Order.id == payment.order_id
                    )
                )

                order_result = await db.execute(
                    order_stmt
                )

                order = (
                    order_result.scalar_one_or_none()
                )

                if order is not None:

                    order.payment_status = "FAILED"

                await db.commit()

        return {"status": "ok"}

    except HTTPException:

        raise

    except Exception:

        await db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed"
        )


# =========================================================
# GET PAYMENT STATUS
# =========================================================

@router.get(
    "/{order_id}",
    response_model=list[PaymentResponse]
)
async def get_payment_status(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        # -------------------------------------------------
        # Verify the order belongs to the user
        # -------------------------------------------------

        order_stmt = (
            select(Order)
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id
            )
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        # -------------------------------------------------
        # Get all payments for this order
        # -------------------------------------------------

        stmt = (
            select(Payment)
            .where(
                Payment.order_id == order_id
            )
            .order_by(
                Payment.created_at.desc()
            )
        )

        result = await db.execute(stmt)

        payments = result.scalars().all()

        return payments

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
