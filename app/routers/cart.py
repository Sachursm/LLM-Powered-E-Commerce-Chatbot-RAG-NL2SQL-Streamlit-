from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.database.models.cart import Cart
from app.database.models.cart_item import CartItem
from app.database.models.product import Product
from app.database.models.user import User
from app.schemas.cart import CartResponse
from app.schemas.cart_item import (
    CartItemCreate,
    CartItemUpdate,
    CartItemResponse
)

from app.core.security import require_active_user


router = APIRouter(
    prefix="/cart",
    tags=["Cart"]
)


@router.post(
    "/items",
    response_model=CartItemResponse,
    status_code=status.HTTP_201_CREATED
)
def add_cart_item(
    item_data: CartItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Check product exists
        product_stmt = select(Product).where(
            Product.id == item_data.product_id
        )

        product = db.execute(
            product_stmt
        ).scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        # Validate quantity
        if item_data.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail="Quantity must be greater than 0"
            )

        # Find user's cart
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        cart = db.execute(
            cart_stmt
        ).scalar_one_or_none()

        # Create cart if it doesn't exist
        if cart is None:
            cart = Cart(
                user_id=current_user.id
            )

            db.add(cart)
            db.flush()

        # Check whether product is already in cart
        existing_stmt = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == item_data.product_id
        )

        existing_item = db.execute(
            existing_stmt
        ).scalar_one_or_none()

        # If already exists, increase quantity
        if existing_item is not None:

            existing_item.quantity += item_data.quantity

            db.commit()
            db.refresh(existing_item)

            return existing_item

        # Create new cart item
        cart_item = CartItem(
            cart_id=cart.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity
        )

        db.add(cart_item)

        db.commit()
        db.refresh(cart_item)

        return cart_item

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.get(
    "",
    response_model=CartResponse
)
def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        cart = db.execute(
            stmt
        ).scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        return cart

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.patch(
    "/items/{item_id}",
    response_model=CartItemResponse
)
def update_cart_item(
    item_id: int,
    item_data: CartItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Validate quantity
        if item_data.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail="Quantity must be greater than 0"
            )

        # Find current user's cart
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        cart = db.execute(
            cart_stmt
        ).scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # Find item inside user's cart
        item_stmt = select(CartItem).where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id
        )

        cart_item = db.execute(
            item_stmt
        ).scalar_one_or_none()

        if cart_item is None:
            raise HTTPException(
                status_code=404,
                detail="Cart item not found"
            )

        cart_item.quantity = item_data.quantity

        db.commit()
        db.refresh(cart_item)

        return cart_item

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_cart_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Find current user's cart
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        cart = db.execute(
            cart_stmt
        ).scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # Find item inside user's cart
        item_stmt = select(CartItem).where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id
        )

        cart_item = db.execute(
            item_stmt
        ).scalar_one_or_none()

        if cart_item is None:
            raise HTTPException(
                status_code=404,
                detail="Cart item not found"
            )

        db.delete(cart_item)

        db.commit()

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )

@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT
)
def clear_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Find current user's cart
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        cart = db.execute(
            cart_stmt
        ).scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # Find all items in the cart
        items_stmt = select(CartItem).where(
            CartItem.cart_id == cart.id
        )

        cart_items = db.execute(
            items_stmt
        ).scalars().all()

        # Delete all cart items
        for cart_item in cart_items:
            db.delete(cart_item)

        db.commit()

    except SQLAlchemyError:
        db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )