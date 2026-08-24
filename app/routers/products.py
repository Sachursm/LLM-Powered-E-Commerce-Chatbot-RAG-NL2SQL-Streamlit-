from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.models.product import Product
from app.schemas.product import ProductResponse
from app.database.dependencies import get_db
from sqlalchemy.exc import SQLAlchemyError


router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


@router.get("/", response_model=list[ProductResponse])
def get_products(db: Session = Depends(get_db)):

    try:
        stmt = select(Product)
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