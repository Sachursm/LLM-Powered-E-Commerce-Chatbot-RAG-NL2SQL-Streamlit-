from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

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

from app.core.security import  require_admin_or_seller


router = APIRouter(
    prefix="/seller/products",
    tags=["Seller Products"]
)


@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_seller_product(
    product_data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends( require_admin_or_seller)
):
    try:
        # Find the category using an async database query.
        category_stmt = select(Category).where(
            Category.name == product_data.category
        )

        result = await db.execute(category_stmt)
        category = result.scalar_one_or_none()

        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        # Create a completely new product.
        # A seller can create a product even if another seller
        # already sells a similar product.
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

        # Flush so SQLAlchemy generates product.id before
        # creating the SellerProduct relationship.
        await db.flush()

        # Connect the newly created product to the current seller.
        seller_product = SellerProduct(
            seller_id=current_user.id,
            product_id=product.id
        )

        db.add(seller_product)

        # Record who created the product.
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="PRODUCT",
            target_id=product.id,
            action="PRODUCT_CREATED",
            old_value=None,
            new_value=product.name
        )

        db.add(audit_log)

        # Save the product, seller relationship, and audit log
        # as one database transaction.
        await db.commit()

        # Refresh the product so its database-generated values
        # are available in the response.
        await db.refresh(product)

        return ProductResponse(
            id=product.id,
            source_product_id=product.source_product_id,
            name=product.name,
            description=product.description,
            price=product.price,
            stock=product.stock,
            image_url=product.image_url,
            rating=product.rating,
            ratings_count=product.ratings_count,
            category_id=product.category_id,
            seller_id=current_user.id
        )

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.get(
    "/",
    response_model=list[ProductResponse]
)
async def get_my_products(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends( require_admin_or_seller)
):
    try:
        # Get only the products that belong to the current seller.
        stmt = (
            select(Product, SellerProduct.seller_id)
            .join(
                SellerProduct,
                SellerProduct.product_id == Product.id
            )
            .where(
                SellerProduct.seller_id == current_user.id
            )
        )

        result = await db.execute(stmt)
        products = result.all()

        # Include seller_id in every product response.
        return [
            ProductResponse(
                id=product.id,
                source_product_id=product.source_product_id,
                name=product.name,
                description=product.description,
                price=product.price,
                stock=product.stock,
                image_url=product.image_url,
                rating=product.rating,
                ratings_count=product.ratings_count,
                category_id=product.category_id,
                seller_id=seller_id
            )
            for product, seller_id in products
        ]

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.patch(
    "/{product_id}",
    response_model=ProductResponse
)
async def update_seller_product(
    product_id: int,
    product_data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends( require_admin_or_seller)
):
    try:
        # Find the product only if it belongs to the current seller.
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

        result = await db.execute(stmt)
        product = result.scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found in your products"
            )

        # Get only fields that were actually provided.
        update_data = product_data.model_dump(
            exclude_unset=True
        )

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        # Handle category separately because Product stores
        # category_id rather than the category name.
        if "category" in update_data:

            category_stmt = select(Category).where(
                Category.name == update_data["category"]
            )

            result = await db.execute(category_stmt)
            category = result.scalar_one_or_none()

            if category is None:
                raise HTTPException(
                    status_code=404,
                    detail="Category not found"
                )

            old_category_id = product.category_id

            product.category_id = category.id

            # Record the category change.
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

        # Update the remaining product fields.
        for field, value in update_data.items():

            old_value = getattr(product, field)

            setattr(product, field, value)

            # Record every changed field in the audit log.
            audit_log = AuditLog(
                actor_user_id=current_user.id,
                target_type="PRODUCT",
                target_id=product.id,
                action=f"{field.upper()}_CHANGED",
                old_value=str(old_value),
                new_value=str(value)
            )

            db.add(audit_log)

        await db.commit()
        await db.refresh(product)

        return ProductResponse(
            id=product.id,
            source_product_id=product.source_product_id,
            name=product.name,
            description=product.description,
            price=product.price,
            stock=product.stock,
            image_url=product.image_url,
            rating=product.rating,
            ratings_count=product.ratings_count,
            category_id=product.category_id,
            seller_id=current_user.id
        )

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_seller_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends( require_admin_or_seller)
):
    try:
        # Make sure the product belongs to the current seller.
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

        result = await db.execute(stmt)
        product = result.scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found in your products"
            )

        # Create the audit record before deleting the product.
        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="PRODUCT",
            target_id=product.id,
            action="PRODUCT_DELETED",
            old_value=product.name,
            new_value=None
        )

        db.add(audit_log)

        # Delete the product.
        # The SellerProduct relationship is configured with
        # cascade delete, so its seller relationship is removed too.
        await db.delete(product)

        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )