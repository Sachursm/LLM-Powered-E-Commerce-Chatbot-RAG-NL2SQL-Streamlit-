from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database.dependencies import get_db
from app.database.models.product import Product

router = APIRouter(
    prefix="/products",
    tags=["Products"]
)


@router.get("/")
def get_products(
    db: Session = Depends(get_db)
):
    stmt = select(Product).limit(5)

    products = db.execute(stmt).scalars().all()

    return products