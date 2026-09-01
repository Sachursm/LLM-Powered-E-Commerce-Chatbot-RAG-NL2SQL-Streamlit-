from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db
from app.database.models.category import Category
from app.schemas.category import (
    CategoryResponse,
    CategoryCreate,
    CategoryUpdate
)
from app.database.models.audit_log import AuditLog
from app.database.models.product import Product
from app.core.security import require_admin_or_seller
from app.database.models.user import User


router = APIRouter(
    prefix="/categories",
    tags=["Categories"]
)


# ---------------------------------------------------------
# GET ALL CATEGORIES
# ---------------------------------------------------------
# Returns all categories ordered alphabetically by name.
# This endpoint does not require authentication.
# ---------------------------------------------------------

@router.get(
    "/",
    response_model=list[CategoryResponse]
)
async def get_categories(
    db: AsyncSession = Depends(get_db)
):
    try:
        stmt = select(Category).order_by(Category.name)

        # Execute the query asynchronously
        result = await db.execute(stmt)

        # Convert the result into Category objects
        categories = result.scalars().all()

        return categories

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# ---------------------------------------------------------
# GET CATEGORY BY NAME
# ---------------------------------------------------------
# Allows the user to request a category using its name.
# ---------------------------------------------------------

@router.get(
    "/by-name/{category_name}",
    response_model=CategoryResponse
)
async def get_category_by_name(
    category_name: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        stmt = select(Category).where(
            Category.name == category_name
        )

        # Execute query asynchronously
        result = await db.execute(stmt)

        category = result.scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        return category

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# ---------------------------------------------------------
# CREATE CATEGORY
# ---------------------------------------------------------
# Only ADMIN or SELLER can create a category.
#
# We first check whether a category with the same name
# already exists.
# ---------------------------------------------------------

@router.post(
    "/",
    response_model=CategoryResponse,
    status_code=201
)
async def create_category(
    category_data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):
    try:
        # Check whether the category already exists
        stmt = select(Category).where(
            Category.name == category_data.name
        )

        result = await db.execute(stmt)

        existing_category = result.scalar_one_or_none()

        if existing_category is not None:
            raise HTTPException(
                status_code=409,
                detail="Category already exists"
            )

        # Create the category
        category = Category(
            name=category_data.name
        )

        db.add(category)

        # Flush so that category.id is generated
        # before creating the audit log.
        await db.flush()

        # Record who created the category
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="CATEGORY",
            target_id=category.id,
            action="CATEGORY_CREATED",
            old_value=None,
            new_value=category.name
        )

        db.add(audit_log)

        # Save category and audit log together
        await db.commit()

        # Refresh category with the database-generated values
        await db.refresh(category)

        return category

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# ---------------------------------------------------------
# UPDATE CATEGORY
# ---------------------------------------------------------
# Only ADMIN or SELLER can update a category.
#
# A category name cannot be changed to a name that is
# already being used by another category.
# ---------------------------------------------------------

@router.patch(
    "/{category_id}",
    response_model=CategoryResponse
)
async def update_category(
    category_id: int,
    category_data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):
    try:
        # Find the category being updated
        stmt = select(Category).where(
            Category.id == category_id
        )

        result = await db.execute(stmt)

        category = result.scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        # Check whether another category already uses
        # the requested name.
        existing_stmt = select(Category).where(
            Category.name == category_data.name,
            Category.id != category_id
        )

        existing_result = await db.execute(
            existing_stmt
        )

        existing_category = existing_result.scalar_one_or_none()

        if existing_category is not None:
            raise HTTPException(
                status_code=409,
                detail="Category name already exists"
            )

        # Keep the old name for the audit log
        old_name = category.name

        # Update category name
        category.name = category_data.name

        # Record the change
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="CATEGORY",
            target_id=category.id,
            action="CATEGORY_UPDATED",
            old_value=old_name,
            new_value=category.name
        )

        db.add(audit_log)

        # Save both changes
        await db.commit()

        await db.refresh(category)

        return category

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# ---------------------------------------------------------
# DELETE CATEGORY
# ---------------------------------------------------------
# Only ADMIN or SELLER can delete a category.
#
# A category cannot be deleted if any product is currently
# using that category.
# ---------------------------------------------------------

@router.delete(
    "/{category_id}",
    status_code=204
)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):
    try:
        # Find the category
        stmt = select(Category).where(
            Category.id == category_id
        )

        result = await db.execute(stmt)

        category = result.scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        # Check whether products are using this category
        product_stmt = select(Product).where(
            Product.category_id == category_id
        )

        product_result = await db.execute(
            product_stmt
        )

        products = product_result.scalars().all()

        if products:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete category because products are using it"
            )

        # Record deletion in the audit log
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="CATEGORY",
            target_id=category.id,
            action="CATEGORY_DELETED",
            old_value=category.name,
            new_value=None
        )

        db.add(audit_log)

        # Delete the category
        await db.delete(category)

        # Save deletion and audit log
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )