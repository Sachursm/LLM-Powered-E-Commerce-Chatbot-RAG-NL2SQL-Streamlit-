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

from app.core.security import require_admin


router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


# =========================================================
# GET ALL PRODUCTS
# =========================================================
# Returns BOTH:
#
# 1. Admin/imported products
# 2. Seller products
#
# IMPORTANT:
#
# SellerProduct is connected using OUTER JOIN.
#
# This is required because some admin/imported products
# do not have a row inside seller_products.
#
# If a product has a SellerProduct row:
#     seller_id = actual seller ID
#
# If a product does not have a SellerProduct row:
#     seller_id = None
#
# Therefore ALL products can be displayed.
# =========================================================

@router.get(
    "/",
    response_model=list[ProductResponse]
)
async def get_products(
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    db: AsyncSession = Depends(get_db)
):
    try:

        stmt = (
            select(
                Product,
                SellerProduct.seller_id
            )
            .outerjoin(
                SellerProduct,
                SellerProduct.product_id == Product.id
            )
        )

        # -------------------------------------------------
        # SEARCH FILTER
        # -------------------------------------------------

        if search is not None:

            stmt = stmt.where(
                Product.name.ilike(f"%{search}%")
            )

        # -------------------------------------------------
        # CATEGORY FILTER
        # -------------------------------------------------

        if category is not None:

            stmt = (
                stmt
                .join(
                    Category,
                    Category.id == Product.category_id
                )
                .where(
                    Category.name == category
                )
            )

        # -------------------------------------------------
        # MINIMUM PRICE FILTER
        # -------------------------------------------------

        if min_price is not None:

            stmt = stmt.where(
                Product.price >= min_price
            )

        # -------------------------------------------------
        # MAXIMUM PRICE FILTER
        # -------------------------------------------------

        if max_price is not None:

            stmt = stmt.where(
                Product.price <= max_price
            )

        # -------------------------------------------------
        # SORT
        # -------------------------------------------------

        if sort_by == "price_low":

            stmt = stmt.order_by(Product.price.asc())

        elif sort_by == "price_high":

            stmt = stmt.order_by(Product.price.desc())

        elif sort_by == "rating":

            stmt = stmt.order_by(
                Product.rating.desc().nulls_last()
            )

        elif sort_by == "name":

            stmt = stmt.order_by(Product.name.asc())

        else:

            stmt = stmt.order_by(Product.id.asc())

        result = await db.execute(stmt)

        rows = result.all()

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
            for product, seller_id in rows
        ]

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

# =========================================================
# GET SINGLE PRODUCT
# =========================================================
# Returns BOTH admin and seller products.
#
# We use OUTER JOIN instead of INNER JOIN.
#
# Therefore:
#
# GET /products/1
#
# will work even if product 1 does not exist in
# seller_products.
# =========================================================

@router.get(
    "/{product_id}",
    response_model=ProductResponse
)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db)
):
    try:

        # Find product and optionally its seller.
        #
        # OUTER JOIN means a product can exist without
        # a SellerProduct record.
        stmt = (
            select(
                Product,
                SellerProduct.seller_id
            )
            .outerjoin(
                SellerProduct,
                SellerProduct.product_id == Product.id
            )
            .where(
                Product.id == product_id
            )
        )

        # Execute asynchronously.
        result = await db.execute(stmt)

        # Get one matching row.
        row = result.first()

        # Product does not exist at all.
        if row is None:

            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        product, seller_id = row

        # Return product information.
        #
        # seller_id can be:
        #
        # actual seller ID
        #
        # OR
        #
        # None for an imported/admin product that does not
        # have a SellerProduct record.
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
            seller_id=seller_id
        )

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# CREATE PRODUCT
# =========================================================
# Only ADMIN can create products through this route.
#
# The product is connected to the admin through
# SellerProduct.
#
# This keeps seller_id OUT of the products table.
# =========================================================

@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_product(
    product_data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        # -------------------------------------------------
        # FIND CATEGORY
        # -------------------------------------------------

        category_stmt = select(Category).where(
            Category.name == product_data.category
        )

        category_result = await db.execute(
            category_stmt
        )

        category = category_result.scalar_one_or_none()

        if category is None:

            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )

        # -------------------------------------------------
        # CREATE PRODUCT
        # -------------------------------------------------

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

        # Get generated product ID.
        await db.flush()

        # -------------------------------------------------
        # CONNECT PRODUCT TO ADMIN
        # -------------------------------------------------

        seller_product = SellerProduct(
            seller_id=current_user.id,
            product_id=product.id
        )

        db.add(seller_product)

        # -------------------------------------------------
        # AUDIT LOG
        # -------------------------------------------------

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="PRODUCT",
            target_id=product.id,
            action="PRODUCT_CREATED",
            old_value=None,
            new_value=product.name
        )

        db.add(audit_log)

        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        await db.commit()

        await db.refresh(product)

        # -------------------------------------------------
        # RETURN RESPONSE
        # -------------------------------------------------

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


# =========================================================
# UPDATE PRODUCT
# =========================================================
# Only ADMIN can update products.
# =========================================================

@router.patch(
    "/{product_id}",
    response_model=ProductResponse
)
async def update_product(
    product_id: int,
    product_data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        # -------------------------------------------------
        # FIND PRODUCT
        # -------------------------------------------------

        stmt = select(Product).where(
            Product.id == product_id
        )

        result = await db.execute(stmt)

        product = result.scalar_one_or_none()

        if product is None:

            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        # -------------------------------------------------
        # GET ONLY PROVIDED FIELDS
        # -------------------------------------------------

        update_data = product_data.model_dump(
            exclude_unset=True
        )

        if not update_data:

            raise HTTPException(
                status_code=400,
                detail="No fields provided for update"
            )

        # -------------------------------------------------
        # CATEGORY UPDATE
        # -------------------------------------------------

        if "category" in update_data:

            category_stmt = select(Category).where(
                Category.name == update_data["category"]
            )

            category_result = await db.execute(
                category_stmt
            )

            category = category_result.scalar_one_or_none()

            if category is None:

                raise HTTPException(
                    status_code=404,
                    detail="Category not found"
                )

            old_category_id = product.category_id

            product.category_id = category.id

            # Audit category change.
            audit_log = AuditLog(
                actor_user_id=current_user.id,
                target_type="PRODUCT",
                target_id=product.id,
                action="CATEGORY_CHANGED",
                old_value=str(old_category_id),
                new_value=str(category.id)
            )

            db.add(audit_log)

            # Remove category from normal field updates.
            del update_data["category"]

        # -------------------------------------------------
        # UPDATE OTHER FIELDS
        # -------------------------------------------------

        for field, value in update_data.items():

            old_value = getattr(
                product,
                field
            )

            setattr(
                product,
                field,
                value
            )

            # Audit every changed field.
            audit_log = AuditLog(
                actor_user_id=current_user.id,
                target_type="PRODUCT",
                target_id=product.id,
                action=f"{field.upper()}_CHANGED",
                old_value=str(old_value),
                new_value=str(value)
            )

            db.add(audit_log)

        # -------------------------------------------------
        # COMMIT CHANGES
        # -------------------------------------------------

        await db.commit()

        await db.refresh(product)

        # -------------------------------------------------
        # FIND SELLER
        # -------------------------------------------------
        #
        # Some old/imported admin products may not have
        # a SellerProduct record.
        #
        # Therefore we use scalar_one_or_none().
        # -------------------------------------------------

        seller_stmt = select(
            SellerProduct.seller_id
        ).where(
            SellerProduct.product_id == product.id
        )

        seller_result = await db.execute(
            seller_stmt
        )

        seller_id = seller_result.scalar_one_or_none()

        # -------------------------------------------------
        # RETURN UPDATED PRODUCT
        # -------------------------------------------------

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
            seller_id=seller_id
        )

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# DELETE PRODUCT
# =========================================================
# Only ADMIN can delete products.
# =========================================================

@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:

        # -------------------------------------------------
        # FIND PRODUCT
        # -------------------------------------------------

        stmt = select(Product).where(
            Product.id == product_id
        )

        result = await db.execute(stmt)

        product = result.scalar_one_or_none()

        if product is None:

            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        # -------------------------------------------------
        # AUDIT BEFORE DELETE
        # -------------------------------------------------

        audit_log = AuditLog(
            actor_user_id=current_user.id,
            target_type="PRODUCT",
            target_id=product.id,
            action="PRODUCT_DELETED",
            old_value=product.name,
            new_value=None
        )

        db.add(audit_log)

        # -------------------------------------------------
        # DELETE PRODUCT
        # -------------------------------------------------

        await db.delete(product)

        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        await db.commit()

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )