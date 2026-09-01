from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

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
async def add_cart_item(
    item_data: CartItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Check whether the requested product exists.
        product_stmt = select(Product).where(
            Product.id == item_data.product_id
        )

        result = await db.execute(product_stmt)
        product = result.scalar_one_or_none()

        if product is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        # Quantity must always be greater than zero.
        if item_data.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail="Quantity must be greater than 0"
            )

        # Find the current user's cart.
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        result = await db.execute(cart_stmt)
        cart = result.scalar_one_or_none()

        # Create a cart automatically if the user does not have one.
        if cart is None:
            cart = Cart(
                user_id=current_user.id
            )

            db.add(cart)
            await db.flush()

        # Check whether this product is already in the cart.
        existing_stmt = select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == item_data.product_id
        )

        result = await db.execute(existing_stmt)
        existing_item = result.scalar_one_or_none()

        # If the product already exists, increase its quantity.
        if existing_item is not None:
            existing_item.quantity += item_data.quantity

            await db.commit()
            await db.refresh(existing_item)

            return existing_item

        # Otherwise create a new cart item.
        cart_item = CartItem(
            cart_id=cart.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity
        )

        db.add(cart_item)

        await db.commit()
        await db.refresh(cart_item)

        return cart_item

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.get(
    "",
    response_model=CartResponse
)
async def get_cart(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Find the cart belonging to the current user.
        stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        result = await db.execute(stmt)
        cart = result.scalar_one_or_none()

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
async def update_cart_item(
    item_id: int,
    item_data: CartItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Quantity must be greater than zero.
        if item_data.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail="Quantity must be greater than 0"
            )

        # Find the current user's cart.
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        result = await db.execute(cart_stmt)
        cart = result.scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # Find the requested item inside the user's own cart.
        item_stmt = select(CartItem).where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id
        )

        result = await db.execute(item_stmt)
        cart_item = result.scalar_one_or_none()

        if cart_item is None:
            raise HTTPException(
                status_code=404,
                detail="Cart item not found"
            )

        # Replace the existing quantity with the new quantity.
        cart_item.quantity = item_data.quantity

        await db.commit()
        await db.refresh(cart_item)

        return cart_item

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_cart_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Find the current user's cart.
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        result = await db.execute(cart_stmt)
        cart = result.scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # Make sure the item belongs to this user's cart.
        item_stmt = select(CartItem).where(
            CartItem.id == item_id,
            CartItem.cart_id == cart.id
        )

        result = await db.execute(item_stmt)
        cart_item = result.scalar_one_or_none()

        if cart_item is None:
            raise HTTPException(
                status_code=404,
                detail="Cart item not found"
            )

        # Delete the selected cart item.
        await db.delete(cart_item)

        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT
)
async def clear_cart(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:
        # Find the current user's cart.
        cart_stmt = select(Cart).where(
            Cart.user_id == current_user.id
        )

        result = await db.execute(cart_stmt)
        cart = result.scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # Find all items belonging to this cart.
        items_stmt = select(CartItem).where(
            CartItem.cart_id == cart.id
        )

        result = await db.execute(items_stmt)
        cart_items = result.scalars().all()

        # Delete every item from the cart.
        for cart_item in cart_items:
            await db.delete(cart_item)

        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )