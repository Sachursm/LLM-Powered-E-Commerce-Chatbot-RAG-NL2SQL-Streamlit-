from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.database.models.category import Category
from app.database.models.product import Product
from app.database.models.seller_product import SellerProduct
from app.database.models.audit_log import AuditLog
from app.database.models.user import User

from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate
)

from app.core.security import require_seller


router = APIRouter(
    prefix="/seller/products",
    tags=["Seller Products"]
)


@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED
)
def create_seller_product(
    product_data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_seller)
):
    try:
        # Find category
        category_stmt = select(Category).where(
            Category.name == product_data.category
        )

        category = db.execute(
            category_stmt
        ).scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        # Create product
        product = Product(
            source_product_id=product_data.source_product_id,
            name=product_data.name,
            description=product_data.description,
            price=product_data.price,
            stock=product_data.stock,
            image_url=product_data.image_url,
            category_id=category.id
        )

        db.add(product)
        db.flush()

        # Automatically connect product to this seller
        seller_product = SellerProduct(
            seller_id=current_user.id,
            product_id=product.id
        )

        db.add(seller_product)

        # Audit log
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="PRODUCT",
            target_id=product.id,
            action="PRODUCT_CREATED",
            old_value=None,
            new_value=product.name
        )

        db.add(audit_log)

        db.commit()
        db.refresh(product)

        return product

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.get(
    "/",
    response_model=list[ProductResponse]
)
def get_my_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_seller)
):
    try:
        stmt = (
            select(Product)
            .join(
                SellerProduct,
                SellerProduct.product_id == Product.id
            )
            .where(
                SellerProduct.seller_id == current_user.id
            )
        )

        result = db.execute(stmt)

        return result.scalars().all()

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.patch(
    "/{product_id}",
    response_model=ProductResponse
)
def update_seller_product(
    product_id: int,
    product_data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_seller)
):
    try:
        # Find product owned by current seller
        stmt = (
            select(Product)
            .join(
                SellerProduct,
                SellerProduct.product_id == Product.id
            )
            .where(
                Product.id == product_id,
                SellerProduct.seller_id == current_user.id
            )
        )

        product = db.execute(
            stmt
        ).scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found in your products"
            )

        update_data = product_data.model_dump(
            exclude_unset=True
        )

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        # Category update
        if "category" in update_data:

            category_stmt = select(Category).where(
                Category.name == update_data["category"]
            )

            category = db.execute(
                category_stmt
            ).scalar_one_or_none()

            if category is None:
                raise HTTPException(
                    status_code=404,
                    detail="Category not found"
                )

            old_category_id = product.category_id

            product.category_id = category.id

            audit_log = AuditLog(
                actor_user_id=current_user.id,
                target_type="PRODUCT",
                target_id=product.id,
                action="CATEGORY_CHANGED",
                old_value=str(old_category_id),
                new_value=str(category.id)
            )

            db.add(audit_log)

            del update_data["category"]

        # Update remaining fields
        for field, value in update_data.items():

            old_value = getattr(product, field)

            setattr(product, field, value)

            audit_log = AuditLog(
                actor_user_id=current_user.id,
                target_type="PRODUCT",
                target_id=product.id,
                action=f"{field.upper()}_CHANGED",
                old_value=str(old_value),
                new_value=str(value)
            )

            db.add(audit_log)

        db.commit()
        db.refresh(product)

        return product

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_seller_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_seller)
):
    try:
        # Make sure this product belongs to current seller
        stmt = (
            select(Product)
            .join(
                SellerProduct,
                SellerProduct.product_id == Product.id
            )
            .where(
                Product.id == product_id,
                SellerProduct.seller_id == current_user.id
            )
        )

        product = db.execute(
            stmt
        ).scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found in your products"
            )

        # Audit before deletion
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="PRODUCT",
            target_id=product.id,
            action="PRODUCT_DELETED",
            old_value=product.name,
            new_value=None
        )

        db.add(audit_log)

        # Delete product
        db.delete(product)

        db.commit()

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )