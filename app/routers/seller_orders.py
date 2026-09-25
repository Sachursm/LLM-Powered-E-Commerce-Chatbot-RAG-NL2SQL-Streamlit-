from fastapi import (
    APIRouter, Depends, HTTPException,
    Query, status
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.product import Product
from app.database.models.address import Address
from app.database.models.payment import Payment
from app.database.models.shipment import (
    Shipment,
    ShipmentTracking
)
from app.database.models.address import Address

from app.schemas.shipment import ShipmentResponse


from app.core.security import require_admin_or_seller

from datetime import date, datetime, time

from sqlalchemy import func

from app.schemas.pagination import PaginatedResponse

router = APIRouter(
    prefix="/seller/orders",
    tags=["Seller Orders"]
)


# =========================================================
# SELLER ORDER ITEM RESPONSE
# =========================================================
#
# We define this here because the seller sees a
# different view than the customer.
#
# The seller sees:
#   - order info
#   - only THEIR order items
#   - product name
#   - customer id
#
# The seller does NOT see:
#   - other sellers' items
#   - other sellers' info
#
# =========================================================

from pydantic import BaseModel, ConfigDict
from datetime import datetime


class SellerOrderItemDetail(BaseModel):
    id: int
    order_id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: float
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class SellerOrderResponse(BaseModel):
    order_id: int
    customer_id: int
    order_status: str
    payment_status: str
    order_created_at: datetime
    items: list[SellerOrderItemDetail]

    model_config = ConfigDict(
        from_attributes=True
    )


# =========================================================
# GET SELLER ORDERS
# =========================================================
#
# Returns all orders that contain at least one item
# owned by the authenticated seller.
#
# The seller only sees their own items within
# each order.
#
# =========================================================
@router.get(
    "",
)
async def get_seller_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller),
    skip: int = 0,
    limit: int = 20,
    from_date: date | None = None,
    to_date: date | None = None,
    order_id: int | None = Query(
        None, description="Filter by order ID"
    ),
    order_status: str | None = Query(
        None, description="Filter by order status"
    ),
    payment_status: str | None = Query(
        None, description="Filter by payment status"
    ),
    product_id: int | None = Query(
        None, description="Filter by product ID"
    ),
    customer_id: int | None = Query(
        None, description="Filter by customer ID"
    )
):

    try:

        stmt = (
            select(
                OrderItem,
                Order,
                Product.name.label("product_name")
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .join(
                Product,
                Product.id == OrderItem.product_id
            )
            .where(
                OrderItem.owner_id == current_user.id
            )
        )

        if from_date is not None:

            from_datetime = datetime.combine(
                from_date, time.min
            )

            stmt = stmt.where(
                Order.created_at >= from_datetime
            )

        if to_date is not None:

            to_datetime = datetime.combine(
                to_date, time.max
            )

            stmt = stmt.where(
                Order.created_at <= to_datetime
            )

        if order_id is not None:

            stmt = stmt.where(
                Order.id == order_id
            )

        if order_status is not None:

            stmt = stmt.where(
                Order.status == order_status.upper()
            )

        if payment_status is not None:

            stmt = stmt.where(
                Order.payment_status == (
                    payment_status.upper()
                )
            )

        if product_id is not None:

            stmt = stmt.where(
                OrderItem.product_id == product_id
            )

        if customer_id is not None:

            stmt = stmt.where(
                Order.user_id == customer_id
            )

        stmt = stmt.order_by(
            Order.created_at.desc()
        )

        result = await db.execute(stmt)

        rows = result.all()

        # Group items by order
        orders_dict = {}

        for order_item, order, product_name in rows:

            if order.id not in orders_dict:

                orders_dict[order.id] = (
                    SellerOrderResponse(
                        order_id=order.id,
                        customer_id=order.user_id,
                        order_status=order.status,
                        payment_status=(
                            order.payment_status
                        ),
                        order_created_at=(
                            order.created_at
                        ),
                        items=[]
                    )
                )

            orders_dict[order.id].items.append(
                SellerOrderItemDetail(
                    id=order_item.id,
                    order_id=order_item.order_id,
                    product_id=order_item.product_id,
                    product_name=product_name,
                    quantity=order_item.quantity,
                    unit_price=order_item.unit_price,
                    created_at=order_item.created_at
                )
            )

        all_orders = list(orders_dict.values())

        total = len(all_orders)

        paginated = all_orders[skip:skip + limit]

        return {
            "items": paginated,
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
# GET SINGLE SELLER ORDER
# =========================================================

@router.get(
    "/{order_id}",
    response_model=SellerOrderResponse
)
async def get_seller_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        stmt = (
            select(
                OrderItem,
                Order,
                Product.name.label("product_name")
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .join(
                Product,
                Product.id == OrderItem.product_id
            )
            .where(
                OrderItem.owner_id == current_user.id,
                Order.id == order_id
            )
        )

        result = await db.execute(stmt)

        rows = result.all()

        # -------------------------------------------------
        # No items found for this seller in this order
        # -------------------------------------------------

        if not rows:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        # -------------------------------------------------
        # Build response
        # -------------------------------------------------

        first_order = rows[0][1]

        items = [
            SellerOrderItemDetail(
                id=order_item.id,
                order_id=order_item.order_id,
                product_id=order_item.product_id,
                product_name=product_name,
                quantity=order_item.quantity,
                unit_price=order_item.unit_price,
                created_at=order_item.created_at
            )
            for order_item, order, product_name in rows
        ]

        return SellerOrderResponse(
            order_id=first_order.id,
            customer_id=first_order.user_id,
            order_status=first_order.status,
            payment_status=first_order.payment_status,
            order_created_at=first_order.created_at,
            items=items
        )

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
# GENERATE SHIPPING BILL
# =========================================================
#
# Returns all information needed to ship the order:
#
# - Customer details
# - Shipping address
# - Seller details
# - Products, quantities, prices
# - Payment info
# - Order total
#
# Only shows items belonging to the authenticated
# seller/admin.
#
# =========================================================

@router.get(
    "/{order_id}/shipping-bill"
)
async def get_shipping_bill(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        # -------------------------------------------------
        # Find order items belonging to this seller
        # -------------------------------------------------

        stmt = (
            select(
                OrderItem,
                Order,
                Product
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .join(
                Product,
                Product.id == OrderItem.product_id
            )
            .where(
                OrderItem.owner_id == current_user.id,
                Order.id == order_id
            )
        )

        result = await db.execute(stmt)

        rows = result.all()

        if not rows:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        order = rows[0][1]

        # -------------------------------------------------
        # Check order is eligible for shipping
        # -------------------------------------------------

        if order.status not in ("CONFIRMED", "SHIPPED"):

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Order is '{order.status}'. "
                    f"Only confirmed orders can "
                    f"be shipped"
                )
            )

        if order.payment_status != "PAID":

            raise HTTPException(
                status_code=400,
                detail="Order is not paid yet"
            )

        # -------------------------------------------------
        # Get customer info
        # -------------------------------------------------

        customer_stmt = (
            select(User)
            .where(
                User.id == order.user_id
            )
        )

        customer_result = await db.execute(
            customer_stmt
        )

        customer = customer_result.scalar_one_or_none()

        # -------------------------------------------------
        # Get shipping address
        # -------------------------------------------------

        address = None

        if order.shipping_address_id is not None:

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

        # -------------------------------------------------
        # Get payment info
        # -------------------------------------------------

        payment_stmt = (
            select(Payment)
            .where(
                Payment.order_id == order.id,
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

        payment = payment_result.scalar_one_or_none()

        # -------------------------------------------------
        # Build items list
        # -------------------------------------------------

        items = []
        total_amount = 0

        for order_item, _, product in rows:

            subtotal = (
                order_item.unit_price *
                order_item.quantity
            )

            total_amount += subtotal

            items.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": order_item.quantity,
                "unit_price": order_item.unit_price,
                "subtotal": subtotal
            })

        # -------------------------------------------------
        # Build shipping bill
        # -------------------------------------------------

        shipping_bill = {

            "order_id": order.id,
            "order_status": order.status,
            "order_date": (
                order.created_at.isoformat()
            ),

            "customer": {
                "id": customer.id,
                "username": customer.username,
                "email": customer.email
            } if customer else None,

            "shipping_address": {
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
            } if address else None,

            "seller": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email
            },

            "items": items,

            "total_amount": total_amount,

            "payment": {
                "method": payment.method,
                "status": payment.status,
                "gateway": payment.gateway,
                "paid_at": (
                    payment.updated_at.isoformat()
                )
            } if payment else None

        }

        return shipping_bill

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
# SHIP ORDER
# =========================================================
#
# Seller marks their items as shipped.
#
# This updates the order status to SHIPPED.
#
# Later when we add the shipment/tracking system,
# this will also create a Shipment record.
#
# =========================================================

@router.post(
    "/{order_id}/ship",
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED
)
async def ship_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):

    try:

        # -------------------------------------------------
        # Find order items belonging to this seller
        # -------------------------------------------------

        stmt = (
            select(
                OrderItem,
                Order,
                Product.name.label("product_name")
            )
            .join(
                Order,
                Order.id == OrderItem.order_id
            )
            .join(
                Product,
                Product.id == OrderItem.product_id
            )
            .where(
                OrderItem.owner_id == current_user.id,
                Order.id == order_id
            )
        )

        result = await db.execute(stmt)

        rows = result.all()

        if not rows:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        order = rows[0][1]

        # -------------------------------------------------
        # Verify order is eligible for shipping
        # -------------------------------------------------

        if order.status not in ("CONFIRMED", "SHIPPED"):

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Order is '{order.status}'. "
                    f"Only confirmed orders can "
                    f"be shipped"
                )
            )

        if order.payment_status != "PAID":

            raise HTTPException(
                status_code=400,
                detail="Order is not paid yet"
            )

        # -------------------------------------------------
        # Check if this seller already shipped
        # -------------------------------------------------

        existing_stmt = (
            select(Shipment)
            .where(
                Shipment.order_id == order.id,
                Shipment.seller_id == current_user.id
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        existing_shipment = (
            existing_result.scalar_one_or_none()
        )

        if existing_shipment is not None:

            raise HTTPException(
                status_code=400,
                detail=(
                    "You have already shipped "
                    "this order"
                )
            )

        # -------------------------------------------------
        # Create Shipment
        # -------------------------------------------------

        shipment = Shipment(
            order_id=order.id,
            seller_id=current_user.id,
            customer_id=order.user_id,
            status="SHIPPED",
            shipping_address_id=(
                order.shipping_address_id
            ),
            shipped_by=current_user.id,
            shipped_at=datetime.utcnow()
        )

        db.add(shipment)

        await db.flush()

        # -------------------------------------------------
        # Create initial tracking event
        # -------------------------------------------------

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="SHIPPED",
            description=(
                f"Order shipped by "
                f"{current_user.username}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        # -------------------------------------------------
        # Update order status
        # -------------------------------------------------
        #
        # If all sellers have shipped, order = SHIPPED
        # If some sellers haven't, order stays CONFIRMED
        #
        # For now we set it to SHIPPED since most
        # orders have one seller.
        # -------------------------------------------------

        order.status = "SHIPPED"

        await db.commit()

        # -------------------------------------------------
        # Reload shipment with tracking
        # -------------------------------------------------

        shipment_stmt = (
            select(Shipment)
            .where(
                Shipment.id == shipment.id
            )
        )

        shipment_result = await db.execute(
            shipment_stmt
        )

        shipment = shipment_result.scalar_one()

        # Manually load tracking events
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

        tracking_events = (
            tracking_result.scalars().all()
        )

        return ShipmentResponse(
            id=shipment.id,
            order_id=shipment.order_id,
            seller_id=shipment.seller_id,
            customer_id=shipment.customer_id,
            status=shipment.status,
            shipping_address_id=(
                shipment.shipping_address_id
            ),
            shipped_by=shipment.shipped_by,
            shipped_at=shipment.shipped_at,
            delivered_at=shipment.delivered_at,
            created_at=shipment.created_at,
            updated_at=shipment.updated_at,
            tracking_events=tracking_events
        )

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
# GET MY SHIPMENTS (seller view)
# =========================================================

@router.get(
    "/shipments",
    response_model=list[ShipmentResponse]
)
async def get_my_shipments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by shipment status"
    )
):

    try:

        stmt = (
            select(Shipment)
            .where(
                Shipment.seller_id == current_user.id
            )
        )

        if status_filter is not None:

            stmt = stmt.where(
                Shipment.status == (
                    status_filter.upper()
                )
            )

        stmt = stmt.order_by(
            Shipment.created_at.desc()
        )

        result = await db.execute(stmt)

        shipments = result.scalars().all()

        # Load tracking for each shipment
        response = []

        for shipment in shipments:

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

            tracking_events = (
                tracking_result.scalars().all()
            )

            response.append(
                ShipmentResponse(
                    id=shipment.id,
                    order_id=shipment.order_id,
                    seller_id=shipment.seller_id,
                    customer_id=shipment.customer_id,
                    status=shipment.status,
                    shipping_address_id=(
                        shipment.shipping_address_id
                    ),
                    shipped_by=shipment.shipped_by,
                    shipped_at=shipment.shipped_at,
                    delivered_at=shipment.delivered_at,
                    created_at=shipment.created_at,
                    updated_at=shipment.updated_at,
                    tracking_events=tracking_events
                )
            )

        return response

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )