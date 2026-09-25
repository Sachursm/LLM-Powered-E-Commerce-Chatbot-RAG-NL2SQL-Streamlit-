import json

from fastapi import (
    APIRouter, Depends, HTTPException, Query, status
)

from sqlalchemy import select,func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, datetime, time


from app.schemas.pagination import PaginatedResponse

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.product import Product
from app.database.models.shipment import (
    Shipment,
    ShipmentTracking
)
from app.database.models.return_request import (
    ReturnRequest
)
from app.database.models.payment import Payment

from app.schemas.return_request import (
    ReturnRequestCreate,
    ReturnRequestResponse,
    ReturnApprove,
    ReturnReject
)

from app.core.security import (
    require_active_user,
    require_admin
)


router = APIRouter(
    tags=["Returns"]
)


# =========================================================
# CUSTOMER: CREATE RETURN REQUEST
# =========================================================

@router.post(
    "/orders/{order_id}/items/{item_id}/return",
    response_model=ReturnRequestResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_return_request(
    order_id: int,
    item_id: int,
    return_data: ReturnRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        # -------------------------------------------------
        # Verify order belongs to customer
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
        # Order must be delivered
        # -------------------------------------------------

        if order.status != "DELIVERED":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Returns can only be requested "
                    "for delivered orders"
                )
            )

        # -------------------------------------------------
        # Verify order item exists
        # -------------------------------------------------

        item_stmt = (
            select(OrderItem)
            .where(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id
            )
        )

        item_result = await db.execute(item_stmt)

        order_item = item_result.scalar_one_or_none()

        if order_item is None:

            raise HTTPException(
                status_code=404,
                detail="Order item not found"
            )

        # -------------------------------------------------
        # Check for existing return request
        # -------------------------------------------------

        existing_stmt = (
            select(ReturnRequest)
            .where(
                ReturnRequest.order_item_id == item_id,
                ReturnRequest.status.not_in(
                    ["REJECTED", "COMPLETED"]
                )
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        if existing_result.scalar_one_or_none():

            raise HTTPException(
                status_code=400,
                detail=(
                    "A return request already "
                    "exists for this item"
                )
            )

        # -------------------------------------------------
        # Validate type and reason
        # -------------------------------------------------

        valid_types = [
            "RETURN", "REPLACE", "EXCHANGE"
        ]

        if return_data.type.upper() not in valid_types:

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid type. Must be: "
                    f"{', '.join(valid_types)}"
                )
            )

        valid_reasons = [
            "DAMAGED", "WRONG_SIZE", "DEFECTIVE",
            "WRONG_PRODUCT", "OTHER"
        ]

        if return_data.reason.upper() not in valid_reasons:

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid reason. Must be: "
                    f"{', '.join(valid_reasons)}"
                )
            )

        # -------------------------------------------------
        # Create return request
        # -------------------------------------------------

        images_json = None

        if return_data.images:

            images_json = json.dumps(
                return_data.images
            )

        return_request = ReturnRequest(
            order_id=order.id,
            order_item_id=order_item.id,
            product_id=order_item.product_id,
            user_id=current_user.id,
            type=return_data.type.upper(),
            reason=return_data.reason.upper(),
            description=return_data.description,
            images=images_json,
            status="PENDING"
        )

        db.add(return_request)

        await db.commit()

        await db.refresh(return_request)

        return return_request

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
# CUSTOMER: GET MY RETURNS
# =========================================================

@router.get(
    "/orders/{order_id}/returns",
    response_model=list[ReturnRequestResponse]
)
async def get_my_returns(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        order_stmt = (
            select(Order)
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id
            )
        )

        order_result = await db.execute(order_stmt)

        if order_result.scalar_one_or_none() is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        stmt = (
            select(ReturnRequest)
            .where(
                ReturnRequest.order_id == order_id,
                ReturnRequest.user_id == current_user.id
            )
            .order_by(
                ReturnRequest.created_at.desc()
            )
        )

        result = await db.execute(stmt)

        return result.scalars().all()

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
# ADMIN: GET ALL RETURNS
# =========================================================

@router.get(
    "/admin/returns",
    response_model=PaginatedResponse[ReturnRequestResponse]
)
async def get_all_returns(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    skip: int = 0,
    limit: int = 20,
    from_date: date | None = None,
    to_date: date | None = None,
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by status"
    ),
    user_id: int | None = None,
    order_id: int | None = None
):

    try:

        stmt = select(ReturnRequest)

        count_stmt = select(
            func.count(ReturnRequest.id)
        )

        if from_date is not None:

            from_datetime = datetime.combine(
                from_date, time.min
            )

            stmt = stmt.where(
                ReturnRequest.created_at >= from_datetime
            )

            count_stmt = count_stmt.where(
                ReturnRequest.created_at >= from_datetime
            )

        if to_date is not None:

            to_datetime = datetime.combine(
                to_date, time.max
            )

            stmt = stmt.where(
                ReturnRequest.created_at <= to_datetime
            )

            count_stmt = count_stmt.where(
                ReturnRequest.created_at <= to_datetime
            )

        if status_filter is not None:

            stmt = stmt.where(
                ReturnRequest.status == (
                    status_filter.upper()
                )
            )

            count_stmt = count_stmt.where(
                ReturnRequest.status == (
                    status_filter.upper()
                )
            )

        if user_id is not None:

            stmt = stmt.where(
                ReturnRequest.user_id == user_id
            )

            count_stmt = count_stmt.where(
                ReturnRequest.user_id == user_id
            )

        if order_id is not None:

            stmt = stmt.where(
                ReturnRequest.order_id == order_id
            )

            count_stmt = count_stmt.where(
                ReturnRequest.order_id == order_id
            )

        total_result = await db.execute(count_stmt)

        total = total_result.scalar()

        stmt = (
            stmt
            .order_by(ReturnRequest.created_at.desc())
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
# ADMIN: GET SINGLE RETURN
# =========================================================

@router.get(
    "/admin/returns/{return_id}"
)
async def get_return_detail(
    return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(ReturnRequest)
            .where(ReturnRequest.id == return_id)
        )

        result = await db.execute(stmt)

        return_request = result.scalar_one_or_none()

        if return_request is None:

            raise HTTPException(
                status_code=404,
                detail="Return request not found"
            )

        # Get product info
        product_stmt = (
            select(Product)
            .where(
                Product.id == return_request.product_id
            )
        )

        product_result = await db.execute(
            product_stmt
        )

        product = product_result.scalar_one_or_none()

        # Get customer info
        customer_stmt = (
            select(User)
            .where(
                User.id == return_request.user_id
            )
        )

        customer_result = await db.execute(
            customer_stmt
        )

        customer = customer_result.scalar_one_or_none()

        # Get order item
        item_stmt = (
            select(OrderItem)
            .where(
                OrderItem.id == (
                    return_request.order_item_id
                )
            )
        )

        item_result = await db.execute(item_stmt)

        order_item = item_result.scalar_one_or_none()

        # Parse images
        images = None

        if return_request.images:

            images = json.loads(
                return_request.images
            )

        return {
            "return_request": {
                "id": return_request.id,
                "type": return_request.type,
                "reason": return_request.reason,
                "description": (
                    return_request.description
                ),
                "images": images,
                "status": return_request.status,
                "resolution": (
                    return_request.resolution
                ),
                "admin_notes": (
                    return_request.admin_notes
                ),
                "created_at": (
                    return_request.created_at
                    .isoformat()
                )
            },
            "customer": {
                "id": customer.id,
                "username": customer.username,
                "email": customer.email
            } if customer else None,
            "product": {
                "id": product.id,
                "name": product.name,
                "price": product.price
            } if product else None,
            "order_item": {
                "quantity": order_item.quantity,
                "unit_price": order_item.unit_price
            } if order_item else None
        }

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
# ADMIN: APPROVE RETURN
# =========================================================
#
# Creates a RETURN shipment assigned to a hub.
# The hub manager then assigns an agent for pickup.
# Same flow as delivery but in reverse.
#
# =========================================================

@router.patch(
    "/admin/returns/{return_id}/approve"
)
async def approve_return(
    return_id: int,
    approve_data: ReturnApprove,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        # -------------------------------------------------
        # Find return request
        # -------------------------------------------------

        stmt = (
            select(ReturnRequest)
            .where(ReturnRequest.id == return_id)
        )

        result = await db.execute(stmt)

        return_request = result.scalar_one_or_none()

        if return_request is None:

            raise HTTPException(
                status_code=404,
                detail="Return request not found"
            )

        if return_request.status != "PENDING":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Return is '{return_request.status}'. "
                    f"Can only approve pending returns"
                )
            )

        # -------------------------------------------------
        # Validate resolution
        # -------------------------------------------------

        valid_resolutions = [
            "REFUND", "REPLACE", "EXCHANGE"
        ]

        if approve_data.resolution.upper() not in (
            valid_resolutions
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid resolution. Must be: "
                    f"{', '.join(valid_resolutions)}"
                )
            )

        # -------------------------------------------------
        # Verify destination hub exists
        # -------------------------------------------------

        from app.database.models.delivery_hub import (
            DeliveryHub
        )

        hub_stmt = (
            select(DeliveryHub)
            .where(
                DeliveryHub.id == (
                    approve_data.destination_hub_id
                )
            )
        )

        hub_result = await db.execute(hub_stmt)

        hub = hub_result.scalar_one_or_none()

        if hub is None:

            raise HTTPException(
                status_code=404,
                detail="Destination hub not found"
            )

        # -------------------------------------------------
        # Get original order info
        # -------------------------------------------------

        order_stmt = (
            select(Order)
            .where(
                Order.id == return_request.order_id
            )
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        # Get owner from order item
        item_stmt = (
            select(OrderItem)
            .where(
                OrderItem.id == (
                    return_request.order_item_id
                )
            )
        )

        item_result = await db.execute(item_stmt)

        order_item = item_result.scalar_one_or_none()

        # -------------------------------------------------
        # Create return shipment
        # -------------------------------------------------

        return_shipment = Shipment(
            order_id=return_request.order_id,
            seller_id=(
                order_item.owner_id
                if order_item else 0
            ),
            customer_id=return_request.user_id,
            type="RETURN",
            status="RETURN_PICKUP_PENDING",
            shipping_address_id=(
                order.shipping_address_id
                if order else None
            )
        )

        db.add(return_shipment)

        await db.flush()

        # -------------------------------------------------
        # Create tracking event
        # -------------------------------------------------

        tracking = ShipmentTracking(
            shipment_id=return_shipment.id,
            status="RETURN_APPROVED",
            description=(
                f"Return approved. "
                f"Resolution: "
                f"{approve_data.resolution.upper()}. "
                f"Pickup hub: {hub.name}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        # -------------------------------------------------
        # Update return request
        # -------------------------------------------------

        return_request.status = "APPROVED"
        return_request.resolution = (
            approve_data.resolution.upper()
        )
        return_request.return_shipment_id = (
            return_shipment.id
        )
        return_request.reviewed_by = current_user.id
        return_request.reviewed_at = datetime.utcnow()
        return_request.admin_notes = (
            approve_data.admin_notes
        )

        # -------------------------------------------------
        # Update order status
        # -------------------------------------------------

        if order is not None:

            order.status = "RETURN_INITIATED"

        await db.commit()

        return {
            "return_id": return_request.id,
            "status": return_request.status,
            "resolution": return_request.resolution,
            "return_shipment_id": return_shipment.id,
            "pickup_hub": hub.name,
            "message": (
                f"Return approved. "
                f"Hub manager at {hub.name} can now "
                f"assign a pickup agent"
            )
        }

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
# ADMIN: REJECT RETURN
# =========================================================

@router.patch(
    "/admin/returns/{return_id}/reject"
)
async def reject_return(
    return_id: int,
    reject_data: ReturnReject,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(ReturnRequest)
            .where(ReturnRequest.id == return_id)
        )

        result = await db.execute(stmt)

        return_request = result.scalar_one_or_none()

        if return_request is None:

            raise HTTPException(
                status_code=404,
                detail="Return request not found"
            )

        if return_request.status != "PENDING":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Return is '{return_request.status}'. "
                    f"Can only reject pending returns"
                )
            )

        return_request.status = "REJECTED"
        return_request.reviewed_by = current_user.id
        return_request.reviewed_at = datetime.utcnow()
        return_request.admin_notes = (
            reject_data.admin_notes
        )

        await db.commit()

        return {
            "return_id": return_request.id,
            "status": "REJECTED",
            "admin_notes": reject_data.admin_notes,
            "message": "Return request rejected"
        }

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
# ADMIN: COMPLETE RETURN (process resolution)
# =========================================================

@router.post(
    "/admin/returns/{return_id}/complete"
)
async def complete_return(
    return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(ReturnRequest)
            .where(ReturnRequest.id == return_id)
        )

        result = await db.execute(stmt)

        return_request = result.scalar_one_or_none()

        if return_request is None:

            raise HTTPException(
                status_code=404,
                detail="Return request not found"
            )

        if return_request.status != "APPROVED":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Return must be approved "
                    "before completing"
                )
            )

        # -------------------------------------------------
        # Process based on resolution
        # -------------------------------------------------

        message = ""

        if return_request.resolution == "REFUND":

            # Find original payment
            payment_stmt = (
                select(Payment)
                .where(
                    Payment.order_id == (
                        return_request.order_id
                    ),
                    Payment.status == "SUCCESS"
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

                payment.status = "REFUNDED"
                payment.gateway_status = "refunded"

            # Get order item for amount
            item_stmt = (
                select(OrderItem)
                .where(
                    OrderItem.id == (
                        return_request.order_item_id
                    )
                )
            )

            item_result = await db.execute(item_stmt)

            order_item = (
                item_result.scalar_one_or_none()
            )

            refund_amount = 0

            if order_item:

                refund_amount = (
                    order_item.unit_price *
                    order_item.quantity
                )

            # Restore stock
            product_stmt = (
                select(Product)
                .where(
                    Product.id == (
                        return_request.product_id
                    )
                )
            )

            product_result = await db.execute(
                product_stmt
            )

            product = (
                product_result.scalar_one_or_none()
            )

            if product and order_item:

                product.stock += order_item.quantity

            # Update order payment status
            order_stmt = (
                select(Order)
                .where(
                    Order.id == (
                        return_request.order_id
                    )
                )
            )

            order_result = await db.execute(
                order_stmt
            )

            order = order_result.scalar_one_or_none()

            if order:

                order.payment_status = "REFUNDED"
                order.status = "RETURNED"

            message = (
                f"Refund of ₹{refund_amount} "
                f"processed"
            )

        elif return_request.resolution in (
            "REPLACE", "EXCHANGE"
        ):

            order_stmt = (
                select(Order)
                .where(
                    Order.id == (
                        return_request.order_id
                    )
                )
            )

            order_result = await db.execute(
                order_stmt
            )

            order = order_result.scalar_one_or_none()

            if order:

                order.status = "RETURNED"

            message = (
                f"{return_request.resolution} "
                f"will be processed. "
                f"A new shipment will be created"
            )

        # -------------------------------------------------
        # Update return request
        # -------------------------------------------------

        return_request.status = "COMPLETED"

        # -------------------------------------------------
        # Update return shipment
        # -------------------------------------------------

        if return_request.return_shipment_id:

            shipment_stmt = (
                select(Shipment)
                .where(
                    Shipment.id == (
                        return_request
                        .return_shipment_id
                    )
                )
            )

            shipment_result = await db.execute(
                shipment_stmt
            )

            shipment = (
                shipment_result.scalar_one_or_none()
            )

            if shipment:

                shipment.status = "RETURN_COMPLETED"

                tracking = ShipmentTracking(
                    shipment_id=shipment.id,
                    status="RETURN_COMPLETED",
                    description=(
                        f"Return completed. "
                        f"Resolution: "
                        f"{return_request.resolution}"
                    ),
                    created_by=current_user.id
                )

                db.add(tracking)

        await db.commit()

        return {
            "return_id": return_request.id,
            "status": "COMPLETED",
            "resolution": return_request.resolution,
            "message": message
        }

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
# RETURN BILL (generated when product reaches hub)
# =========================================================

@router.get(
    "/admin/returns/{return_id}/return-bill"
)
async def get_return_bill(
    return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(ReturnRequest)
            .where(ReturnRequest.id == return_id)
        )

        result = await db.execute(stmt)

        return_request = result.scalar_one_or_none()

        if return_request is None:

            raise HTTPException(
                status_code=404,
                detail="Return request not found"
            )

        if return_request.status not in (
            "APPROVED", "COMPLETED"
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Return bill can only be "
                    "generated after approval"
                )
            )

        # Get shipment
        shipment = None

        if return_request.return_shipment_id:

            shipment_stmt = (
                select(Shipment)
                .where(
                    Shipment.id == (
                        return_request
                        .return_shipment_id
                    )
                )
            )

            shipment_result = await db.execute(
                shipment_stmt
            )

            shipment = (
                shipment_result.scalar_one_or_none()
            )

        # Get hub info
        from app.database.models.delivery_hub import (
            DeliveryHub
        )

        hub_info = None

        if shipment and shipment.current_hub_id:

            hub_stmt = (
                select(DeliveryHub)
                .where(
                    DeliveryHub.id == (
                        shipment.current_hub_id
                    )
                )
            )

            hub_result = await db.execute(hub_stmt)

            hub = hub_result.scalar_one_or_none()

            if hub:

                hub_info = {
                    "id": hub.id,
                    "name": hub.name,
                    "address": hub.address,
                    "city": hub.city,
                    "state": hub.state,
                    "pincode": hub.pincode
                }

        # Get customer
        customer_stmt = (
            select(User)
            .where(
                User.id == return_request.user_id
            )
        )

        customer_result = await db.execute(
            customer_stmt
        )

        customer = customer_result.scalar_one_or_none()

        # Get product
        product_stmt = (
            select(Product)
            .where(
                Product.id == return_request.product_id
            )
        )

        product_result = await db.execute(
            product_stmt
        )

        product = product_result.scalar_one_or_none()

        # Get order item
        item_stmt = (
            select(OrderItem)
            .where(
                OrderItem.id == (
                    return_request.order_item_id
                )
            )
        )

        item_result = await db.execute(item_stmt)

        order_item = item_result.scalar_one_or_none()

        # Get seller
        seller_info = None

        if order_item:

            seller_stmt = (
                select(User)
                .where(User.id == order_item.owner_id)
            )

            seller_result = await db.execute(
                seller_stmt
            )

            seller = seller_result.scalar_one_or_none()

            if seller:

                seller_info = {
                    "id": seller.id,
                    "username": seller.username,
                    "email": seller.email
                }

        # Get pickup address
        from app.database.models.address import Address

        address_info = None

        order_stmt = (
            select(Order)
            .where(
                Order.id == return_request.order_id
            )
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order and order.shipping_address_id:

            address_stmt = (
                select(Address)
                .where(
                    Address.id == (
                        order.shipping_address_id
                    )
                )
            )

            address_result = await db.execute(
                address_stmt
            )

            address = (
                address_result.scalar_one_or_none()
            )

            if address:

                address_info = {
                    "full_name": address.full_name,
                    "phone": address.phone,
                    "address_line_1": (
                        address.address_line_1
                    ),
                    "address_line_2": (
                        address.address_line_2
                    ),
                    "city": address.city,
                    "state": address.state,
                    "pincode": address.pincode
                }

        # Parse images
        images = None

        if return_request.images:

            images = json.loads(
                return_request.images
            )

        # Get tracking
        tracking_events = []

        if shipment:

            tracking_stmt = (
                select(ShipmentTracking)
                .where(
                    ShipmentTracking.shipment_id == (
                        shipment.id
                    )
                )
                .order_by(
                    ShipmentTracking.created_at
                )
            )

            tracking_result = await db.execute(
                tracking_stmt
            )

            events = tracking_result.scalars().all()

            tracking_events = [
                {
                    "status": e.status,
                    "description": e.description,
                    "timestamp": (
                        e.created_at.isoformat()
                    )
                }
                for e in events
            ]

        # Build return bill
        refund_amount = 0

        if order_item:

            refund_amount = (
                order_item.unit_price *
                order_item.quantity
            )

        return {
            "return_bill": {
                "return_id": return_request.id,
                "order_id": return_request.order_id,
                "type": return_request.type,
                "reason": return_request.reason,
                "resolution": (
                    return_request.resolution
                ),
                "status": return_request.status,
                "description": (
                    return_request.description
                ),
                "images": images,
                "created_at": (
                    return_request.created_at
                    .isoformat()
                )
            },
            "customer": {
                "id": customer.id,
                "username": customer.username,
                "email": customer.email
            } if customer else None,
            "pickup_address": address_info,
            "product": {
                "id": product.id,
                "name": product.name,
                "price": product.price
            } if product else None,
            "order_item": {
                "quantity": order_item.quantity,
                "unit_price": order_item.unit_price,
                "refund_amount": refund_amount
            } if order_item else None,
            "seller": seller_info,
            "current_hub": hub_info,
            "return_shipment": {
                "id": shipment.id,
                "status": shipment.status,
                "tracking": tracking_events
            } if shipment else None
        }

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