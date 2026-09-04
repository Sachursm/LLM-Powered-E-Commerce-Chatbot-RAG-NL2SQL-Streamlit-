from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.cart import Cart
from app.database.models.cart_item import CartItem
from app.database.models.product import Product
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.seller_product import SellerProduct

from app.schemas.order import OrderResponse

from app.core.security import require_active_user


router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)


# =========================================================
# CREATE ORDER
# =========================================================

@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_order(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):
    try:

        # -------------------------------------------------
        # Find the current user's cart
        # -------------------------------------------------

        cart_stmt = (
            select(Cart)
            .options(
                selectinload(Cart.items)
                .selectinload(CartItem.product)
            )
            .where(
                Cart.user_id == current_user.id
            )
        )

        result = await db.execute(cart_stmt)

        cart = result.scalar_one_or_none()

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # -------------------------------------------------
        # Make sure the cart contains products
        # -------------------------------------------------

        if not cart.items:

            raise HTTPException(
                status_code=400,
                detail="Cart is empty"
            )

        # -------------------------------------------------
        # Create the order
        # -------------------------------------------------

        order = Order(
            user_id=current_user.id,
            status="PENDING"
        )

        db.add(order)

        # Flush so SQLAlchemy generates order.id
        # before creating OrderItems.

        await db.flush()

        # -------------------------------------------------
        # Process every cart item
        # -------------------------------------------------

        for cart_item in cart.items:

            product = cart_item.product

            # ---------------------------------------------
            # Make sure the product still exists
            # ---------------------------------------------

            if product is None:

                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Product {cart_item.product_id} "
                        "not found"
                    )
                )

            # ---------------------------------------------
            # Check stock
            # ---------------------------------------------

            if product.stock < cart_item.quantity:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Insufficient stock for "
                        f"product '{product.name}'. "
                        f"Available stock: {product.stock}"
                    )
                )

            # ---------------------------------------------
            # Find product owner
            # ---------------------------------------------
            #
            # Seller-owned products have an entry in
            # seller_products.
            #
            # Admin-owned products do not have an entry
            # there, so we identify the admin separately.
            # ---------------------------------------------

            seller_stmt = (
                select(SellerProduct)
                .where(
                    SellerProduct.product_id == product.id
                )
                .limit(1)
            )

            seller_result = await db.execute(seller_stmt)

            seller_product = seller_result.scalar_one_or_none()

            if seller_product is not None:

                owner_id = seller_product.seller_id

            else:

                # -----------------------------------------
                # Product has no seller_products entry.
                #
                # Find an active ADMIN user.
                # -----------------------------------------

                admin_stmt = (
                    select(User)
                    .where(
                        User.role == "ADMIN",
                        User.status == "ACTIVE"
                    )
                    .limit(1)
                )

                admin_result = await db.execute(admin_stmt)

                admin_user = admin_result.scalar_one_or_none()

                if admin_user is None:

                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "No active admin account found "
                            "for product ownership"
                        )
                    )

                owner_id = admin_user.id

            # ---------------------------------------------
            # Save the current product price
            # ---------------------------------------------
            #
            # We DO NOT rely on Product.price later.
            #
            # Example:
            #
            # Product price today = ₹3995
            # Customer buys it
            # Product price later = ₹4500
            #
            # OrderItem.unit_price remains ₹3995.
            # ---------------------------------------------

            unit_price = product.price

            # ---------------------------------------------
            # Create OrderItem
            # ---------------------------------------------

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                owner_id=owner_id,
                quantity=cart_item.quantity,
                unit_price=unit_price
            )

            db.add(order_item)

            # ---------------------------------------------
            # Reduce product stock
            # ---------------------------------------------

            product.stock -= cart_item.quantity

        # -------------------------------------------------
        # Clear the cart
        # -------------------------------------------------

        for cart_item in cart.items:

            await db.delete(cart_item)

        # -------------------------------------------------
        # Commit EVERYTHING together
        # -------------------------------------------------
        #
        # If anything above fails, the transaction is
        # rolled back.
        #
        # Therefore we don't end up with:
        #
        # Order created
        # but stock not reduced
        #
        # or:
        #
        # Stock reduced
        # but OrderItem missing.
        # -------------------------------------------------

        await db.commit()

        # -------------------------------------------------
        # Reload the order including its items
        # -------------------------------------------------

        order_stmt = (
            select(Order)
            .options(
                selectinload(Order.items)
            )
            .where(
                Order.id == order.id
            )
        )

        result = await db.execute(order_stmt)

        order = result.scalar_one()

        return order

    except HTTPException:
        # HTTPException is an intentional application
        # error, so rollback and re-raise it.

        await db.rollback()

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# GET MY ORDERS
# =========================================================

@router.get(
    "",
    response_model=list[OrderResponse]
)
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items)
            )
            .where(
                Order.user_id == current_user.id
            )
            .order_by(
                Order.created_at.desc()
            )
        )

        result = await db.execute(stmt)

        orders = result.scalars().all()

        return orders

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# GET ONE ORDER
# =========================================================

@router.get(
    "/{order_id}",
    response_model=OrderResponse
)
async def get_my_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items)
            )
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        order = result.scalar_one_or_none()

        if order is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        return order

    except HTTPException:

        raise

    except SQLAlchemyError:

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )


# =========================================================
# CANCEL ORDER
# =========================================================

@router.patch(
    "/{order_id}/cancel",
    response_model=OrderResponse
)
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        # -------------------------------------------------
        # Find the customer's order
        # -------------------------------------------------

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items)
            )
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        order = result.scalar_one_or_none()

        if order is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        # -------------------------------------------------
        # Only pending orders can currently be cancelled.
        #
        # Later we can expand this logic.
        # -------------------------------------------------

        if order.status != "PENDING":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Only pending orders "
                    "can be cancelled"
                )
            )

        # -------------------------------------------------
        # Return stock to products
        # -------------------------------------------------

        for item in order.items:

            product_stmt = select(Product).where(
                Product.id == item.product_id
            )

            product_result = await db.execute(
                product_stmt
            )

            product = product_result.scalar_one_or_none()

            if product is not None:

                product.stock += item.quantity

        # -------------------------------------------------
        # Update order status
        # -------------------------------------------------

        order.status = "CANCELLED"

        await db.commit()

        # -------------------------------------------------
        # Refresh order with items
        # -------------------------------------------------

        order_stmt = (
            select(Order)
            .options(
                selectinload(Order.items)
            )
            .where(
                Order.id == order.id
            )
        )

        result = await db.execute(order_stmt)

        order = result.scalar_one()

        return order

    except HTTPException:

        await db.rollback()

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable"
        )