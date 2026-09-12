from fastapi import (
    APIRouter, Depends, HTTPException, Query
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

from app.core.security import require_admin

from sqlalchemy.orm import selectinload


router = APIRouter(
    prefix="/admin",
    tags=["Admin Management"]
)


# =========================================================
# DASHBOARD OVERVIEW
# =========================================================

@router.get("/dashboard")
async def admin_dashboard(
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
    response_model=list[OrderResponse]
)
async def get_all_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
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

        if user_id is not None:

            stmt = stmt.where(
                Order.user_id == user_id
            )

        stmt = stmt.order_by(
            Order.created_at.desc()
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
# SINGLE ORDER DETAIL
# =========================================================

@router.get("/orders/{order_id}")
async def get_order_detail(
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
async def get_all_payments(
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
async def get_all_shipments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by shipment status"
    ),
    order_id: int | None = Query(
        None, description="Filter by order ID"
    ),
    seller_id: int | None = Query(
        None, description="Filter by seller ID"
    ),
    hub_id: int | None = Query(
        None, description="Filter by current hub ID"
    ),
    agent_id: int | None = Query(
        None, description="Filter by agent ID"
    )
):

    try:

        stmt = select(Shipment)

        if status_filter is not None:

            stmt = stmt.where(
                Shipment.status == (
                    status_filter.upper()
                )
            )

        if order_id is not None:

            stmt = stmt.where(
                Shipment.order_id == order_id
            )

        if seller_id is not None:

            stmt = stmt.where(
                Shipment.seller_id == seller_id
            )

        if hub_id is not None:

            stmt = stmt.where(
                Shipment.current_hub_id == hub_id
            )

        if agent_id is not None:

            stmt = stmt.where(
                Shipment.assigned_agent_id == agent_id
            )

        stmt = stmt.order_by(
            Shipment.created_at.desc()
        )

        result = await db.execute(stmt)

        shipments = result.scalars().all()

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

            events = tracking_result.scalars().all()

            response.append({
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

        return response

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
async def get_shipment_detail(
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
async def get_audit_logs(
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