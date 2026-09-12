from fastapi import (
    APIRouter, Depends, HTTPException, status
)

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.delivery_hub import DeliveryHub
from app.database.models.delivery_agent import DeliveryAgent

from app.schemas.delivery_agent import (
    DeliveryAgentCreate,
    DeliveryAgentUpdate,
    DeliveryAgentResponse
)

from app.core.security import (
    require_admin,
    require_admin_or_hub_manager
)


router = APIRouter(
    prefix="/delivery/agents",
    tags=["Delivery Agents"]
)


@router.post(
    "",
    response_model=DeliveryAgentResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_agent(
    agent_data: DeliveryAgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):

    try:

        user_stmt = (
            select(User)
            .where(User.id == agent_data.user_id)
        )

        user_result = await db.execute(user_stmt)

        user = user_result.scalar_one_or_none()

        if user is None:

            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        existing_stmt = (
            select(DeliveryAgent)
            .where(
                DeliveryAgent.user_id == (
                    agent_data.user_id
                )
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        if existing_result.scalar_one_or_none():

            raise HTTPException(
                status_code=400,
                detail="User is already a delivery agent"
            )

        hub_stmt = (
            select(DeliveryHub)
            .where(
                DeliveryHub.id == agent_data.hub_id
            )
        )

        hub_result = await db.execute(hub_stmt)

        if hub_result.scalar_one_or_none() is None:

            raise HTTPException(
                status_code=404,
                detail="Hub not found"
            )

        agent = DeliveryAgent(
            user_id=agent_data.user_id,
            hub_id=agent_data.hub_id,
            name=agent_data.name,
            phone=agent_data.phone
        )

        db.add(agent)

        user.role = "DELIVERY_AGENT"

        await db.commit()

        await db.refresh(agent)

        return agent

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
    "",
    response_model=list[DeliveryAgentResponse]
)
async def get_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_hub_manager),
    hub_id: int | None = None
):

    try:

        stmt = select(DeliveryAgent)

        if hub_id is not None:

            stmt = stmt.where(
                DeliveryAgent.hub_id == hub_id
            )

        stmt = stmt.order_by(
            DeliveryAgent.created_at.desc()
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
    "/{agent_id}",
    response_model=DeliveryAgentResponse
)
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_hub_manager)
):

    try:

        stmt = (
            select(DeliveryAgent)
            .where(DeliveryAgent.id == agent_id)
        )

        result = await db.execute(stmt)

        agent = result.scalar_one_or_none()

        if agent is None:

            raise HTTPException(
                status_code=404,
                detail="Agent not found"
            )

        return agent

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
    "/{agent_id}",
    response_model=DeliveryAgentResponse
)
async def update_agent(
    agent_id: int,
    agent_data: DeliveryAgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_hub_manager)
):

    try:

        stmt = (
            select(DeliveryAgent)
            .where(DeliveryAgent.id == agent_id)
        )

        result = await db.execute(stmt)

        agent = result.scalar_one_or_none()

        if agent is None:

            raise HTTPException(
                status_code=404,
                detail="Agent not found"
            )

        update_data = agent_data.model_dump(
            exclude_unset=True
        )

        if not update_data:

            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        if "hub_id" in update_data:

            hub_stmt = (
                select(DeliveryHub)
                .where(
                    DeliveryHub.id == (
                        update_data["hub_id"]
                    )
                )
            )

            hub_result = await db.execute(hub_stmt)

            if hub_result.scalar_one_or_none() is None:

                raise HTTPException(
                    status_code=404,
                    detail="Hub not found"
                )

        for field, value in update_data.items():
            setattr(agent, field, value)

        await db.commit()

        await db.refresh(agent)

        return agent

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