from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.models.product import Product
from app.schemas.product import ProductResponse, ProductCreate
from app.database.dependencies import get_db
from sqlalchemy.exc import SQLAlchemyError
from app.database.models.category import Category



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

@router.get("/", response_model=list[ProductResponse])
def get_products(
    category: str | None = None,
    db: Session = Depends(get_db)
):
    try:
        stmt = select(Product)

        if category is not None:
            stmt = (
                select(Product)
                .join(Category)
                .where(Category.name == category)
            )

        result = db.execute(stmt)

        products = result.scalars().all()

        return products

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    product_data: ProductCreate,
    db: Session = Depends(get_db)
):
    try:
        product = Product(
            source_product_id=product_data.source_product_id,
            name=product_data.name,
            description=product_data.description,
            price=product_data.price,
            stock=product_data.stock,
            image_url=product_data.image_url,
            category_id=product_data.category_id
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