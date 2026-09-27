from fastapi import (
    APIRouter, Depends, HTTPException, Query, Request
)

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.product import Product
from app.database.models.payment import Payment
from app.database.models.shipment import (
    Shipment,
    ShipmentTracking
)
from app.database.models.delivery_hub import DeliveryHub
from app.database.models.delivery_agent import DeliveryAgent

from app.schemas.order import OrderResponse, OrderItemResponse
from app.schemas.payment import PaymentResponse
from app.schemas.shipment import (
    ShipmentResponse,
    ShipmentTrackingResponse
)
from app.database.models.seller_bank import SellerBank
from app.database.models.seller_payout import (
    SellerPayout,
    SellerCommission
)

from app.schemas.seller_payout import (
    CommissionUpdate,
    CommissionResponse,
    SellerPayoutResponse,
    SellerBankResponse,
    PayoutProcess,
    PayoutHold
)
from app.core.security import require_admin
from app.core.rate_limit import limiter, get_user_key

from sqlalchemy.orm import selectinload

from datetime import date, datetime, time

from app.schemas.pagination import PaginatedResponse


router = APIRouter(
    prefix="/admin",
    tags=["Admin Management"]
)


# =========================================================
# DASHBOARD OVERVIEW
# =========================================================

@router.get("/dashboard")
@limiter.limit("20/minute", key_func=get_user_key)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        # Total users by role
        users_result = await db.execute(
            select(
                User.role,
                func.count(User.id)
            )
            .group_by(User.role)
        )

        users_by_role = {
            role: count
            for role, count in users_result.all()
        }

        # Total orders by status
        orders_result = await db.execute(
            select(
                Order.status,
                func.count(Order.id)
            )
            .group_by(Order.status)
        )

        orders_by_status = {
            status: count
            for status, count in orders_result.all()
        }

        # Total payments by status
        payments_result = await db.execute(
            select(
                Payment.status,
                func.count(Payment.id)
            )
            .group_by(Payment.status)
        )

        payments_by_status = {
            status: count
            for status, count in payments_result.all()
        }

        # Total shipments by status
        shipments_result = await db.execute(
            select(
                Shipment.status,
                func.count(Shipment.id)
            )
            .group_by(Shipment.status)
        )

        shipments_by_status = {
            status: count
            for status, count in shipments_result.all()
        }

        # Counts
        total_products = await db.execute(
            select(func.count(Product.id))
        )

        total_hubs = await db.execute(
            select(func.count(DeliveryHub.id))
        )

        total_agents = await db.execute(
            select(func.count(DeliveryAgent.id))
        )

        return {
            "users": users_by_role,
            "orders": orders_by_status,
            "payments": payments_by_status,
            "shipments": shipments_by_status,
            "total_products": (
                total_products.scalar()
            ),
            "total_hubs": total_hubs.scalar(),
            "total_agents": total_agents.scalar()
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
# ALL ORDERS (with filters)
# =========================================================
@router.get(
    "/orders",
    response_model=PaginatedResponse[OrderResponse]
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_all_orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    skip: int = 0,
    limit: int = 20,
    from_date: date | None = None,
    to_date: date | None = None,
    order_status: str | None = Query(
        None, description="Filter by order status"
    ),
    payment_status: str | None = Query(
        None, description="Filter by payment status"
    ),
    user_id: int | None = Query(
        None, description="Filter by customer ID"
    )
):

    try:

        stmt = (
            select(Order)
            .options(selectinload(Order.items))
        )

        count_stmt = select(func.count(Order.id))

        # Date filters
        if from_date is not None:

            from_datetime = datetime.combine(
                from_date, time.min
            )

            stmt = stmt.where(
                Order.created_at >= from_datetime
            )

            count_stmt = count_stmt.where(
                Order.created_at >= from_datetime
            )

        if to_date is not None:

            to_datetime = datetime.combine(
                to_date, time.max
            )

            stmt = stmt.where(
                Order.created_at <= to_datetime
            )

            count_stmt = count_stmt.where(
                Order.created_at <= to_datetime
            )

        # Status filters
        if order_status is not None:

            stmt = stmt.where(
                Order.status == order_status.upper()
            )

            count_stmt = count_stmt.where(
                Order.status == order_status.upper()
            )

        if payment_status is not None:

            stmt = stmt.where(
                Order.payment_status == (
                    payment_status.upper()
                )
            )

            count_stmt = count_stmt.where(
                Order.payment_status == (
                    payment_status.upper()
                )
            )

        if user_id is not None:

            stmt = stmt.where(
                Order.user_id == user_id
            )

            count_stmt = count_stmt.where(
                Order.user_id == user_id
            )

        # Count + paginate
        total_result = await db.execute(count_stmt)

        total = total_result.scalar()

        stmt = (
            stmt
            .order_by(Order.created_at.desc())
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
# SINGLE ORDER DETAIL
# =========================================================

@router.get("/orders/{order_id}")
@limiter.limit("20/minute", key_func=get_user_key)
async def get_order_detail(
    request: Request,
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        # Order with items
        order_stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        # Customer
        customer_stmt = (
            select(User)
            .where(User.id == order.user_id)
        )

        customer_result = await db.execute(
            customer_stmt
        )

        customer = customer_result.scalar_one_or_none()

        # Payments
        payment_stmt = (
            select(Payment)
            .where(Payment.order_id == order.id)
            .order_by(Payment.created_at.desc())
        )

        payment_result = await db.execute(
            payment_stmt
        )

        payments = payment_result.scalars().all()

        # Shipments with tracking
        shipment_stmt = (
            select(Shipment)
            .where(Shipment.order_id == order.id)
        )

        shipment_result = await db.execute(
            shipment_stmt
        )

        shipments = shipment_result.scalars().all()

        shipment_details = []

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

            events = tracking_result.scalars().all()

            shipment_details.append({
                "id": shipment.id,
                "seller_id": shipment.seller_id,
                "status": shipment.status,
                "current_hub_id": (
                    shipment.current_hub_id
                ),
                "assigned_agent_id": (
                    shipment.assigned_agent_id
                ),
                "shipped_at": (
                    shipment.shipped_at.isoformat()
                    if shipment.shipped_at else None
                ),
                "delivered_at": (
                    shipment.delivered_at.isoformat()
                    if shipment.delivered_at else None
                ),
                "tracking": [
                    {
                        "status": e.status,
                        "description": e.description,
                        "created_by": e.created_by,
                        "timestamp": (
                            e.created_at.isoformat()
                        )
                    }
                    for e in events
                ]
            })

        # Order items with product names
        items = []

        for item in order.items:

            product_stmt = (
                select(Product)
                .where(Product.id == item.product_id)
            )

            product_result = await db.execute(
                product_stmt
            )

            product = product_result.scalar_one_or_none()

            items.append({
                "id": item.id,
                "product_id": item.product_id,
                "product_name": (
                    product.name if product else None
                ),
                "owner_id": item.owner_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price
            })

        return {
            "order": {
                "id": order.id,
                "status": order.status,
                "payment_status": order.payment_status,
                "shipping_address_id": (
                    order.shipping_address_id
                ),
                "created_at": (
                    order.created_at.isoformat()
                ),
                "updated_at": (
                    order.updated_at.isoformat()
                )
            },
            "customer": {
                "id": customer.id,
                "username": customer.username,
                "email": customer.email
            } if customer else None,
            "items": items,
            "payments": [
                {
                    "id": p.id,
                    "amount": p.amount,
                    "currency": p.currency,
                    "method": p.method,
                    "gateway": p.gateway,
                    "status": p.status,
                    "created_at": (
                        p.created_at.isoformat()
                    )
                }
                for p in payments
            ],
            "shipments": shipment_details
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
# ALL PAYMENTS (with filters)
# =========================================================

@router.get(
    "/payments",
    response_model=list[PaymentResponse]
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_all_payments(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by payment status"
    ),
    order_id: int | None = Query(
        None, description="Filter by order ID"
    ),
    user_id: int | None = Query(
        None, description="Filter by user ID"
    )
):

    try:

        stmt = select(Payment)

        if status_filter is not None:

            stmt = stmt.where(
                Payment.status == (
                    status_filter.upper()
                )
            )

        if order_id is not None:

            stmt = stmt.where(
                Payment.order_id == order_id
            )

        if user_id is not None:

            stmt = stmt.where(
                Payment.user_id == user_id
            )

        stmt = stmt.order_by(
            Payment.created_at.desc()
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
# ALL SHIPMENTS (with filters)
# =========================================================
@router.get("/shipments")
@limiter.limit("20/minute", key_func=get_user_key)
async def get_all_shipments(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    skip: int = 0,
    limit: int = 20,
    from_date: date | None = None,
    to_date: date | None = None,
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by shipment status"
    ),
    order_id: int | None = None,
    seller_id: int | None = None,
    hub_id: int | None = None,
    agent_id: int | None = None
):

    try:

        stmt = select(Shipment)

        count_stmt = select(
            func.count(Shipment.id)
        )

        if from_date is not None:

            from_datetime = datetime.combine(
                from_date, time.min
            )

            stmt = stmt.where(
                Shipment.created_at >= from_datetime
            )

            count_stmt = count_stmt.where(
                Shipment.created_at >= from_datetime
            )

        if to_date is not None:

            to_datetime = datetime.combine(
                to_date, time.max
            )

            stmt = stmt.where(
                Shipment.created_at <= to_datetime
            )

            count_stmt = count_stmt.where(
                Shipment.created_at <= to_datetime
            )

        if status_filter is not None:

            stmt = stmt.where(
                Shipment.status == (
                    status_filter.upper()
                )
            )

            count_stmt = count_stmt.where(
                Shipment.status == (
                    status_filter.upper()
                )
            )

        if order_id is not None:

            stmt = stmt.where(
                Shipment.order_id == order_id
            )

            count_stmt = count_stmt.where(
                Shipment.order_id == order_id
            )

        if seller_id is not None:

            stmt = stmt.where(
                Shipment.seller_id == seller_id
            )

            count_stmt = count_stmt.where(
                Shipment.seller_id == seller_id
            )

        if hub_id is not None:

            stmt = stmt.where(
                Shipment.current_hub_id == hub_id
            )

            count_stmt = count_stmt.where(
                Shipment.current_hub_id == hub_id
            )

        if agent_id is not None:

            stmt = stmt.where(
                Shipment.assigned_agent_id == agent_id
            )

            count_stmt = count_stmt.where(
                Shipment.assigned_agent_id == agent_id
            )

        total_result = await db.execute(count_stmt)

        total = total_result.scalar()

        stmt = (
            stmt
            .order_by(Shipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(stmt)

        shipments = result.scalars().all()

        # Build response with tracking
        items = []

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

            events = tracking_result.scalars().all()

            items.append({
                "id": shipment.id,
                "order_id": shipment.order_id,
                "seller_id": shipment.seller_id,
                "customer_id": shipment.customer_id,
                "status": shipment.status,
                "current_hub_id": (
                    shipment.current_hub_id
                ),
                "assigned_agent_id": (
                    shipment.assigned_agent_id
                ),
                "shipped_at": (
                    shipment.shipped_at.isoformat()
                    if shipment.shipped_at else None
                ),
                "delivered_at": (
                    shipment.delivered_at.isoformat()
                    if shipment.delivered_at else None
                ),
                "created_at": (
                    shipment.created_at.isoformat()
                ),
                "tracking": [
                    {
                        "status": e.status,
                        "description": e.description,
                        "timestamp": (
                            e.created_at.isoformat()
                        )
                    }
                    for e in events
                ]
            })

        return {
            "items": items,
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
# SINGLE SHIPMENT DETAIL
# =========================================================

@router.get("/shipments/{shipment_id}")
@limiter.limit("20/minute", key_func=get_user_key)
async def get_shipment_detail(
    request: Request,
    shipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        shipment_stmt = (
            select(Shipment)
            .where(Shipment.id == shipment_id)
        )

        shipment_result = await db.execute(
            shipment_stmt
        )

        shipment = shipment_result.scalar_one_or_none()

        if shipment is None:

            raise HTTPException(
                status_code=404,
                detail="Shipment not found"
            )

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

        # Get seller info
        seller_stmt = (
            select(User)
            .where(User.id == shipment.seller_id)
        )

        seller_result = await db.execute(seller_stmt)

        seller = seller_result.scalar_one_or_none()

        # Get customer info
        customer_stmt = (
            select(User)
            .where(User.id == shipment.customer_id)
        )

        customer_result = await db.execute(
            customer_stmt
        )

        customer = customer_result.scalar_one_or_none()

        # Get agent info
        agent_info = None

        if shipment.assigned_agent_id:

            agent_stmt = (
                select(DeliveryAgent)
                .where(
                    DeliveryAgent.id == (
                        shipment.assigned_agent_id
                    )
                )
            )

            agent_result = await db.execute(
                agent_stmt
            )

            agent = agent_result.scalar_one_or_none()

            if agent:

                agent_info = {
                    "id": agent.id,
                    "name": agent.name,
                    "phone": agent.phone,
                    "hub_id": agent.hub_id
                }

        # Get hub info
        hub_info = None

        if shipment.current_hub_id:

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
                    "city": hub.city
                }

        return {
            "shipment": {
                "id": shipment.id,
                "order_id": shipment.order_id,
                "status": shipment.status,
                "shipped_at": (
                    shipment.shipped_at.isoformat()
                    if shipment.shipped_at else None
                ),
                "delivered_at": (
                    shipment.delivered_at.isoformat()
                    if shipment.delivered_at else None
                ),
                "created_at": (
                    shipment.created_at.isoformat()
                )
            },
            "seller": {
                "id": seller.id,
                "username": seller.username,
                "email": seller.email
            } if seller else None,
            "customer": {
                "id": customer.id,
                "username": customer.username,
                "email": customer.email
            } if customer else None,
            "current_hub": hub_info,
            "assigned_agent": agent_info,
            "tracking": [
                {
                    "status": e.status,
                    "description": e.description,
                    "created_by": e.created_by,
                    "timestamp": (
                        e.created_at.isoformat()
                    )
                }
                for e in events
            ]
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
# AUDIT LOGS
# =========================================================

@router.get("/audit-logs")
@limiter.limit("20/minute", key_func=get_user_key)
async def get_audit_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    target_type: str | None = Query(
        None, description="Filter by target type"
    ),
    action: str | None = Query(
        None, description="Filter by action"
    ),
    actor_id: int | None = Query(
        None, description="Filter by actor user ID"
    ),
    limit: int = Query(
        50, description="Number of results"
    )
):

    try:

        from app.database.models.audit_log import (
            AuditLog
        )

        stmt = select(AuditLog)

        if target_type is not None:

            stmt = stmt.where(
                AuditLog.target_type == (
                    target_type.upper()
                )
            )

        if action is not None:

            stmt = stmt.where(
                AuditLog.action == action.upper()
            )

        if actor_id is not None:

            stmt = stmt.where(
                AuditLog.actor_user_id == actor_id
            )

        stmt = stmt.order_by(
            AuditLog.created_at.desc()
        ).limit(limit)

        result = await db.execute(stmt)

        logs = result.scalars().all()

        return [
            {
                "id": log.id,
                "actor_user_id": log.actor_user_id,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "action": log.action,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "created_at": (
                    log.created_at.isoformat()
                )
            }
            for log in logs
        ]

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# ADMIN: SET COMMISSION RATE
# =========================================================

@router.post(
    "/sellers/{seller_id}/commission",
    response_model=CommissionResponse
)
@limiter.limit("20/minute", key_func=get_user_key)
async def set_commission_rate(
    request: Request,
    seller_id: int,
    commission_data: CommissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        if (commission_data.rate < 0 or
                commission_data.rate > 1):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Rate must be between "
                    "0 and 1 (e.g. 0.15 for 15%)"
                )
            )

        seller_stmt = (
            select(User)
            .where(User.id == seller_id)
        )

        seller_result = await db.execute(
            seller_stmt
        )

        if seller_result.scalar_one_or_none() is None:

            raise HTTPException(
                status_code=404,
                detail="Seller not found"
            )

        existing_stmt = (
            select(SellerCommission)
            .where(
                SellerCommission.seller_id == seller_id
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        commission = (
            existing_result.scalar_one_or_none()
        )

        if commission is not None:

            commission.rate = commission_data.rate
            commission.set_by = current_user.id

        else:

            commission = SellerCommission(
                seller_id=seller_id,
                rate=commission_data.rate,
                set_by=current_user.id
            )

            db.add(commission)

        await db.commit()

        await db.refresh(commission)

        return commission

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
# ADMIN: GET COMMISSION RATE
# =========================================================

@router.get(
    "/sellers/{seller_id}/commission",
    response_model=CommissionResponse
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_commission_rate(
    request: Request,
    seller_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(SellerCommission)
            .where(
                SellerCommission.seller_id == seller_id
            )
        )

        result = await db.execute(stmt)

        commission = result.scalar_one_or_none()

        if commission is None:

            raise HTTPException(
                status_code=404,
                detail=(
                    "Commission not set. "
                    "Default is 15%"
                )
            )

        return commission

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
# ADMIN: VIEW ALL PAYOUTS
# =========================================================
@router.get(
    "/payouts",
    response_model=PaginatedResponse[SellerPayoutResponse]
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_all_payouts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    skip: int = 0,
    limit: int = 20,
    from_date: date | None = None,
    to_date: date | None = None,
    status_filter: str | None = Query(
        None, alias="status"
    ),
    seller_id: int | None = None
):

    try:

        stmt = select(SellerPayout)

        count_stmt = select(
            func.count(SellerPayout.id)
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

        if seller_id is not None:

            stmt = stmt.where(
                SellerPayout.seller_id == seller_id
            )

            count_stmt = count_stmt.where(
                SellerPayout.seller_id == seller_id
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
# ADMIN: CHECK ELIGIBLE PAYOUTS
# =========================================================

@router.post("/payouts/check-eligible")
@limiter.limit("20/minute", key_func=get_user_key)
async def check_eligible_payouts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        from datetime import datetime, timezone

        stmt = (
            select(SellerPayout)
            .where(
                SellerPayout.status == "PENDING",
                SellerPayout.eligible_at != None,
                SellerPayout.eligible_at <= (
                    datetime.now(timezone.utc)
                )
            )
        )

        result = await db.execute(stmt)

        payouts = result.scalars().all()

        count = 0

        for payout in payouts:

            payout.status = "ELIGIBLE"
            count += 1

        await db.commit()

        return {
            "message": (
                f"{count} payouts marked as eligible"
            ),
            "count": count
        }

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
# ADMIN: PAYOUT SUMMARY
# =========================================================

@router.get("/payouts/summary")
@limiter.limit("20/minute", key_func=get_user_key)
async def get_admin_payout_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        total_stmt = (
            select(
                func.sum(SellerPayout.payout_amount)
            )
            .where(
                SellerPayout.status == "ELIGIBLE"
            )
        )

        total_result = await db.execute(total_stmt)

        total_eligible = total_result.scalar() or 0

        paid_stmt = (
            select(
                func.sum(SellerPayout.payout_amount)
            )
            .where(
                SellerPayout.status == "PAID"
            )
        )

        paid_result = await db.execute(paid_stmt)

        total_paid = paid_result.scalar() or 0

        hold_stmt = (
            select(
                func.sum(SellerPayout.payout_amount)
            )
            .where(
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
        )

        commission_result = await db.execute(
            commission_stmt
        )

        total_commission = (
            commission_result.scalar() or 0
        )

        pending_count_stmt = (
            select(func.count(SellerPayout.id))
            .where(
                SellerPayout.status == "ELIGIBLE"
            )
        )

        pending_count_result = await db.execute(
            pending_count_stmt
        )

        pending_count = (
            pending_count_result.scalar() or 0
        )

        return {
            "total_eligible_for_payout": total_eligible,
            "total_paid": total_paid,
            "total_on_hold": total_on_hold,
            "total_commission_earned": total_commission,
            "pending_payout_count": pending_count
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
# ADMIN: PROCESS PAYOUT
# =========================================================

@router.post(
    "/payouts/{payout_id}/process"
)
@limiter.limit("20/minute", key_func=get_user_key)
async def process_payout(
    request: Request,
    payout_id: int,
    process_data: PayoutProcess,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        from datetime import datetime, timezone

        stmt = (
            select(SellerPayout)
            .where(SellerPayout.id == payout_id)
        )

        result = await db.execute(stmt)

        payout = result.scalar_one_or_none()

        if payout is None:

            raise HTTPException(
                status_code=404,
                detail="Payout not found"
            )

        if payout.status != "ELIGIBLE":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Payout is '{payout.status}'. "
                    f"Only eligible payouts can "
                    f"be processed"
                )
            )

        bank_stmt = (
            select(SellerBank)
            .where(
                SellerBank.seller_id == (
                    payout.seller_id
                )
            )
        )

        bank_result = await db.execute(bank_stmt)

        bank = bank_result.scalar_one_or_none()

        if bank is None:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Seller has not added "
                    "bank details"
                )
            )

        payout.status = "PAID"
        payout.paid_at = datetime.now(timezone.utc)
        payout.transaction_ref = (
            process_data.transaction_ref
        )
        payout.admin_notes = (
            process_data.admin_notes
        )

        await db.commit()

        return {
            "payout_id": payout.id,
            "status": "PAID",
            "amount": payout.payout_amount,
            "seller_id": payout.seller_id,
            "transaction_ref": (
                payout.transaction_ref
            ),
            "bank": {
                "account_holder": (
                    bank.account_holder
                ),
                "bank_name": bank.bank_name,
                "account_number": (
                    bank.account_number
                ),
                "ifsc_code": bank.ifsc_code
            },
            "message": (
                f"₹{payout.payout_amount} paid "
                f"to {bank.account_holder}"
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
# ADMIN: HOLD PAYOUT
# =========================================================

@router.post(
    "/payouts/{payout_id}/hold"
)
@limiter.limit("20/minute", key_func=get_user_key)
async def hold_payout(
    request: Request,
    payout_id: int,
    hold_data: PayoutHold,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(SellerPayout)
            .where(SellerPayout.id == payout_id)
        )

        result = await db.execute(stmt)

        payout = result.scalar_one_or_none()

        if payout is None:

            raise HTTPException(
                status_code=404,
                detail="Payout not found"
            )

        if payout.status == "PAID":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot hold an already "
                    "paid payout"
                )
            )

        payout.status = "ON_HOLD"
        payout.admin_notes = hold_data.admin_notes

        await db.commit()

        return {
            "payout_id": payout.id,
            "status": "ON_HOLD",
            "admin_notes": hold_data.admin_notes,
            "message": "Payout put on hold"
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
# ADMIN: RELEASE HOLD
# =========================================================

@router.post(
    "/payouts/{payout_id}/release"
)
@limiter.limit("20/minute", key_func=get_user_key)
async def release_payout(
    request: Request,
    payout_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(SellerPayout)
            .where(SellerPayout.id == payout_id)
        )

        result = await db.execute(stmt)

        payout = result.scalar_one_or_none()

        if payout is None:

            raise HTTPException(
                status_code=404,
                detail="Payout not found"
            )

        if payout.status != "ON_HOLD":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Only on-hold payouts "
                    "can be released"
                )
            )

        payout.status = "ELIGIBLE"
        payout.admin_notes = None

        await db.commit()

        return {
            "payout_id": payout.id,
            "status": "ELIGIBLE",
            "message": "Payout released"
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
# ADMIN: VIEW SELLER BANK DETAILS
# =========================================================

@router.get(
    "/sellers/{seller_id}/bank",
    response_model=SellerBankResponse
)
@limiter.limit("20/minute", key_func=get_user_key)
async def get_seller_bank(
    request: Request,
    seller_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        stmt = (
            select(SellerBank)
            .where(
                SellerBank.seller_id == seller_id
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