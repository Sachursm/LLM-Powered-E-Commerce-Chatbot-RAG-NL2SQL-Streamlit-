from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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


@router.get("/", response_model=list[CategoryResponse])
def get_categories(
    db: Session = Depends(get_db)
):
    try:
        stmt = select(Category).order_by(Category.name)

        result = db.execute(stmt)

        categories = result.scalars().all()

        return categories

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.post("/", response_model=CategoryResponse, status_code=201)
def create_category(
    category_data: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):
    try:
        stmt = select(Category).where(
            Category.name == category_data.name
        )

        existing_category = db.execute(
            stmt
        ).scalar_one_or_none()

        if existing_category is not None:
            raise HTTPException(
                status_code=409,
                detail="Category already exists"
            )

        category = Category(
            name=category_data.name
        )

        db.add(category)
        db.flush()

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="CATEGORY",
            target_id=category.id,
            action="CATEGORY_CREATED",
            old_value=None,
            new_value=category.name
        )

        db.add(audit_log)

        db.commit()
        db.refresh(category)

        return category

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.patch(
    "/{category_id}",
    response_model=CategoryResponse
)
def update_category(
    category_id: int,
    category_data: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):
    try:
        stmt = select(Category).where(
            Category.id == category_id
        )

        category = db.execute(
            stmt
        ).scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        existing_stmt = select(Category).where(
            Category.name == category_data.name,
            Category.id != category_id
        )

        existing_category = db.execute(
            existing_stmt
        ).scalar_one_or_none()

        if existing_category is not None:
            raise HTTPException(
                status_code=409,
                detail="Category name already exists"
            )

        old_name = category.name

        category.name = category_data.name

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="CATEGORY",
            target_id=category.id,
            action="CATEGORY_UPDATED",
            old_value=old_name,
            new_value=category.name
        )

        db.add(audit_log)

        db.commit()
        db.refresh(category)

        return category

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.delete(
    "/{category_id}",
    status_code=204
)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_seller)
):
    try:
        stmt = select(Category).where(
            Category.id == category_id
        )

        category = db.execute(
            stmt
        ).scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        product_stmt = select(Product).where(
            Product.category_id == category_id
        )

        products = db.execute(
            product_stmt
        ).scalars().all()

        if products:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete category because products are using it"
            )

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="CATEGORY",
            target_id=category.id,
            action="CATEGORY_DELETED",
            old_value=category.name,
            new_value=None
        )

        db.add(audit_log)

        db.delete(category)

        db.commit()

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )