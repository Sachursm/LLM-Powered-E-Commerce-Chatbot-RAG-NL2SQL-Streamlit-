from fastapi import (
    APIRouter, Depends, HTTPException, status
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.order import Order
from app.database.models.delivery_hub import DeliveryHub
from app.database.models.delivery_agent import DeliveryAgent
from app.database.models.shipment import (
    Shipment,
    ShipmentTracking
)
from app.database.models.seller_payout import (
                SellerPayout
            )
from datetime import timedelta
from app.database.models.hub_manager import HubManager

from app.schemas.shipment import ShipOutRequest
from app.schemas.delivery_agent import DeliveryFailRequest

from app.core.security import (
    require_delivery_agent,
    require_admin_or_hub_manager
)


router = APIRouter(
    prefix="/delivery",
    tags=["Delivery Operations"]
)


# =========================================================
# SHIP-IN
# =========================================================

@router.post(
    "/hubs/{hub_id}/shipments/{shipment_id}/ship-in"
)
async def ship_in(
    hub_id: int,
    shipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_admin_or_hub_manager
    )
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

        if hub.status != "ACTIVE":

            raise HTTPException(
                status_code=400,
                detail="Hub is not active"
            )

        # -------------------------------------------------
        # Verify hub manager authorization
        # -------------------------------------------------

        if current_user.role == "HUB_MANAGER":

            manager_stmt = (
                select(HubManager)
                .where(
                    HubManager.user_id == (
                        current_user.id
                    ),
                    HubManager.hub_id == hub_id
                )
            )

            manager_result = await db.execute(
                manager_stmt
            )

            if manager_result.scalar_one_or_none() is None:

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "You are not authorized "
                        "to manage this hub"
                    )
                )

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

        if shipment.status not in (
            "SHIPPED", "IN_TRANSIT"
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Shipment is '{shipment.status}'. "
                    f"Cannot ship-in"
                )
            )

        shipment.current_hub_id = hub.id
        shipment.status = "ARRIVED_AT_HUB"

        order_stmt = (
            select(Order)
            .where(Order.id == shipment.order_id)
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is not None:

            order.status = "IN_TRANSIT"

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="ARRIVED_AT_HUB",
            description=(
                f"Arrived at {hub.name}, "
                f"{hub.city}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        await db.commit()

        return {
            "shipment_id": shipment.id,
            "status": shipment.status,
            "current_hub": hub.name,
            "city": hub.city,
            "message": (
                f"Shipment arrived at {hub.name}"
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
# SHIP-OUT
# =========================================================

@router.post(
    "/hubs/{hub_id}/shipments/{shipment_id}/ship-out"
)
async def ship_out(
    hub_id: int,
    shipment_id: int,
    ship_out_data: ShipOutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_admin_or_hub_manager
    )
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

        # -------------------------------------------------
        # Verify hub manager authorization
        # -------------------------------------------------

        if current_user.role == "HUB_MANAGER":

            manager_stmt = (
                select(HubManager)
                .where(
                    HubManager.user_id == (
                        current_user.id
                    ),
                    HubManager.hub_id == hub_id
                )
            )

            manager_result = await db.execute(
                manager_stmt
            )

            if manager_result.scalar_one_or_none() is None:

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "You are not authorized "
                        "to manage this hub"
                    )
                )

        dest_stmt = (
            select(DeliveryHub)
            .where(
                DeliveryHub.id == (
                    ship_out_data.destination_hub_id
                )
            )
        )

        dest_result = await db.execute(dest_stmt)

        dest_hub = dest_result.scalar_one_or_none()

        if dest_hub is None:

            raise HTTPException(
                status_code=404,
                detail="Destination hub not found"
            )

        if dest_hub.id == hub.id:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Destination hub cannot be "
                    "the same as current hub"
                )
            )

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

        if shipment.current_hub_id != hub.id:

            raise HTTPException(
                status_code=400,
                detail="Shipment is not at this hub"
            )

        if shipment.status != "ARRIVED_AT_HUB":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Shipment is '{shipment.status}'. "
                    f"Cannot ship-out"
                )
            )

        shipment.status = "IN_TRANSIT"
        shipment.current_hub_id = None

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="DEPARTED_FROM_HUB",
            description=(
                f"Departed from {hub.name}, "
                f"{hub.city} → "
                f"{dest_hub.name}, {dest_hub.city}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        await db.commit()

        return {
            "shipment_id": shipment.id,
            "status": shipment.status,
            "from_hub": hub.name,
            "to_hub": dest_hub.name,
            "message": (
                f"Shipment departed from "
                f"{hub.name} to {dest_hub.name}"
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
# ASSIGN SHIPMENT TO AGENT
# =========================================================

@router.post(
    "/agents/{agent_id}/shipments/{shipment_id}/assign"
)
async def assign_shipment(
    agent_id: int,
    shipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_admin_or_hub_manager
    )
):

    try:

        agent_stmt = (
            select(DeliveryAgent)
            .where(DeliveryAgent.id == agent_id)
        )

        agent_result = await db.execute(agent_stmt)

        agent = agent_result.scalar_one_or_none()

        if agent is None:

            raise HTTPException(
                status_code=404,
                detail="Agent not found"
            )

        if agent.status != "ACTIVE":

            raise HTTPException(
                status_code=400,
                detail="Agent is not active"
            )

        # -------------------------------------------------
        # Verify hub manager authorization
        # -------------------------------------------------

        if current_user.role == "HUB_MANAGER":

            manager_stmt = (
                select(HubManager)
                .where(
                    HubManager.user_id == (
                        current_user.id
                    ),
                    HubManager.hub_id == agent.hub_id
                )
            )

            manager_result = await db.execute(
                manager_stmt
            )

            if manager_result.scalar_one_or_none() is None:

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "You are not authorized "
                        "to assign agents at this hub"
                    )
                )

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

        if shipment.current_hub_id != agent.hub_id:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Shipment is not at "
                    "the agent's hub"
                )
            )

        if shipment.status != "ARRIVED_AT_HUB":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Shipment is '{shipment.status}'. "
                    f"Must be at hub to assign"
                )
            )

        shipment.assigned_agent_id = agent.id
        shipment.status = "ASSIGNED"

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="ASSIGNED",
            description=(
                f"Assigned to delivery agent "
                f"{agent.name}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        await db.commit()

        return {
            "shipment_id": shipment.id,
            "status": shipment.status,
            "assigned_to": agent.name,
            "agent_phone": agent.phone,
            "message": (
                f"Shipment assigned to {agent.name}"
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
# AGENT TAKES SHIPMENT
# =========================================================

@router.post(
    "/agents/me/shipments/{shipment_id}/take"
)
async def take_shipment(
    shipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_delivery_agent)
):

    try:

        agent_stmt = (
            select(DeliveryAgent)
            .where(
                DeliveryAgent.user_id == current_user.id
            )
        )

        agent_result = await db.execute(agent_stmt)

        agent = agent_result.scalar_one_or_none()

        if agent is None:

            raise HTTPException(
                status_code=404,
                detail="Agent profile not found"
            )

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

        if shipment.assigned_agent_id != agent.id:

            raise HTTPException(
                status_code=403,
                detail="Shipment is not assigned to you"
            )

        if shipment.status != "ASSIGNED":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Shipment is '{shipment.status}'. "
                    f"Cannot take"
                )
            )

        shipment.status = "OUT_FOR_DELIVERY"
        shipment.current_hub_id = None

        order_stmt = (
            select(Order)
            .where(Order.id == shipment.order_id)
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is not None:

            order.status = "OUT_FOR_DELIVERY"

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="OUT_FOR_DELIVERY",
            description=(
                f"Out for delivery by {agent.name}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        await db.commit()

        return {
            "shipment_id": shipment.id,
            "status": shipment.status,
            "agent": agent.name,
            "message": "Shipment picked up for delivery"
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
# AGENT DELIVERS SHIPMENT
# =========================================================

@router.post(
    "/agents/me/shipments/{shipment_id}/deliver"
)
async def deliver_shipment(
    shipment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_delivery_agent)
):

    try:

        agent_stmt = (
            select(DeliveryAgent)
            .where(
                DeliveryAgent.user_id == current_user.id
            )
        )

        agent_result = await db.execute(agent_stmt)

        agent = agent_result.scalar_one_or_none()

        if agent is None:

            raise HTTPException(
                status_code=404,
                detail="Agent profile not found"
            )

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

        if shipment.assigned_agent_id != agent.id:

            raise HTTPException(
                status_code=403,
                detail="Shipment is not assigned to you"
            )

        if shipment.status != "OUT_FOR_DELIVERY":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Shipment is '{shipment.status}'. "
                    f"Must be out for delivery"
                )
            )

        shipment.status = "DELIVERED"
        shipment.delivered_at = datetime.utcnow()

        order_stmt = (
            select(Order)
            .where(Order.id == shipment.order_id)
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is not None:

            order.status = "DELIVERED"

            # ---------------------------------
            # Update payout eligibility
            # ---------------------------------
            payout_stmt = (
                select(SellerPayout)
                .where(
                    SellerPayout.order_id == order.id,
                    SellerPayout.status == "PENDING"
                )
            )

            payout_result = await db.execute(
                payout_stmt
            )

            payouts = payout_result.scalars().all()

            for p in payouts:

                p.eligible_at = (
                    datetime.utcnow() +
                    timedelta(minutes=1)   # timedelta(days=7)
                )

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="DELIVERED",
            description=(
                f"Delivered by {agent.name}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        await db.commit()

        return {
            "shipment_id": shipment.id,
            "status": shipment.status,
            "delivered_at": (
                shipment.delivered_at.isoformat()
            ),
            "agent": agent.name,
            "message": "Shipment delivered successfully"
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
# AGENT FAILS DELIVERY
# =========================================================

@router.post(
    "/agents/me/shipments/{shipment_id}/fail"
)
async def fail_delivery(
    shipment_id: int,
    fail_data: DeliveryFailRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_delivery_agent)
):

    try:

        agent_stmt = (
            select(DeliveryAgent)
            .where(
                DeliveryAgent.user_id == current_user.id
            )
        )

        agent_result = await db.execute(agent_stmt)

        agent = agent_result.scalar_one_or_none()

        if agent is None:

            raise HTTPException(
                status_code=404,
                detail="Agent profile not found"
            )

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

        if shipment.assigned_agent_id != agent.id:

            raise HTTPException(
                status_code=403,
                detail="Shipment is not assigned to you"
            )

        if shipment.status != "OUT_FOR_DELIVERY":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Shipment is '{shipment.status}'. "
                    f"Must be out for delivery"
                )
            )

        valid_reasons = [
            "CUSTOMER_NOT_AVAILABLE",
            "WRONG_ADDRESS",
            "CUSTOMER_REFUSED",
            "DAMAGED_PACKAGE",
            "OTHER"
        ]

        if fail_data.reason.upper() not in valid_reasons:

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid reason. Must be one of: "
                    f"{', '.join(valid_reasons)}"
                )
            )

        shipment.status = "DELIVERY_FAILED"

        order_stmt = (
            select(Order)
            .where(Order.id == shipment.order_id)
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is not None:

            order.status = "DELIVERY_FAILED"

        tracking = ShipmentTracking(
            shipment_id=shipment.id,
            status="DELIVERY_FAILED",
            description=(
                f"Delivery failed: "
                f"{fail_data.reason.upper()}. "
                f"Agent: {agent.name}"
            ),
            created_by=current_user.id
        )

        db.add(tracking)

        await db.commit()

        return {
            "shipment_id": shipment.id,
            "status": shipment.status,
            "reason": fail_data.reason.upper(),
            "agent": agent.name,
            "message": (
                f"Delivery failed: "
                f"{fail_data.reason.upper()}"
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