from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
 
from app.database.dependencies import get_db
from app.database.models.category import Category
from app.database.models.product import Product
from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate
)

from app.core.security import require_admin
from app.database.models.user import User
 
router = APIRouter(
    prefix="/products",
    tags=["Products"]
)
 
 
@router.get("/", response_model=list[ProductResponse])
def get_products(
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    db: Session = Depends(get_db)
):
    try:
        stmt = select(Product)
 
        if category is not None:
            stmt = stmt.join(Category).where(
                Category.name == category
            )
 
        if min_price is not None:
            stmt = stmt.where(
                Product.price >= min_price
            )
 
        if max_price is not None:
            stmt = stmt.where(
                Product.price <= max_price
            )
 
        result = db.execute(stmt)
 
        products = result.scalars().all()
 
        return products
 
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )
 
 
@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    try:
        stmt = select(Product).where(Product.id == product_id)
 
        result = db.execute(stmt)
 
        product = result.scalar_one_or_none()
 
        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )
 
        return product
 
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )
 
 
@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED
)
def create_product(
    product_data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:
        category_stmt = select(Category).where(
            Category.name == product_data.category
        )
 
        category = db.execute(category_stmt).scalar_one_or_none()
 
        if category is None:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )
 
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
        db.commit()
        db.refresh(product)
 
        return product
 
    except SQLAlchemyError:
        db.rollback()
 
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.patch(
    "/{product_id}",
    response_model=ProductResponse
)
def update_product(
    product_id: int,
    product_data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:
        stmt = select(Product).where(
            Product.id == product_id
        )

        result = db.execute(stmt)

        product = result.scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        update_data = product_data.model_dump(
            exclude_unset=True
        )

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

            product.category_id = category.id

            del update_data["category"]

        for field, value in update_data.items():
            setattr(product, field, value)

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
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    try:
        stmt = select(Product).where(
            Product.id == product_id
        )

        result = db.execute(stmt)

        product = result.scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        db.delete(product)
        db.commit()

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )