from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.engine import CursorResult
from typing import cast

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.cart import Cart
from app.database.models.cart_item import CartItem
from app.database.models.product import Product
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.seller_product import SellerProduct
from app.database.models.payment import Payment
from app.database.models.address import Address

from app.schemas.order import (
    OrderResponse,
    CreateOrderRequest
)

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
    order_data: CreateOrderRequest,
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
            )
            .where(
                Cart.user_id == current_user.id
            )
        )

        result = await db.execute(cart_stmt)

        cart = result.scalar_one_or_none()

        # -------------------------------------------------
        # Cart does not exist
        # -------------------------------------------------

        if cart is None:
            raise HTTPException(
                status_code=404,
                detail="Cart not found"
            )

        # -------------------------------------------------
        # Cart is empty
        # -------------------------------------------------
        if not cart.items:
            raise HTTPException(
                status_code=400,
                detail="Cart is empty"
            )

        # -------------------------------------------------
        # Validate shipping address
        # -------------------------------------------------

        address_stmt = (
            select(Address)
            .where(
                Address.id == order_data.shipping_address_id,
                Address.user_id == current_user.id
            )
        )

        address_result = await db.execute(address_stmt)

        address = address_result.scalar_one_or_none()

        if address is None:

            raise HTTPException(
                status_code=404,
                detail="Shipping address not found"
            )

        # -------------------------------------------------
        # Create Order
        # -------------------------------------------------

        order = Order(
            user_id=current_user.id,
            status="PENDING_PAYMENT",
            shipping_address_id=address.id
        )

        db.add(order)

        # Generate order.id
        await db.flush()

        # -------------------------------------------------
        # Process every cart item
        # -------------------------------------------------

        for cart_item in cart.items:

            # ---------------------------------------------
            # Get the current product
            # ---------------------------------------------

            product_stmt = (
                select(Product)
                .where(
                    Product.id == cart_item.product_id
                )
            )

            product_result = await db.execute(
                product_stmt
            )

            product = product_result.scalar_one_or_none()

            # ---------------------------------------------
            # Product does not exist
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
            # Save price BEFORE stock update
            # ---------------------------------------------
            #
            # The order should remember the price at the
            # time of purchase.
            #
            # Product.price can change later.
            # ---------------------------------------------

            unit_price = product.price

            # ---------------------------------------------
            # ATOMIC STOCK UPDATE
            # ---------------------------------------------
            #
            # Stock is reduced ONLY if:
            #
            # Product.id matches
            # AND
            # Product.stock >= requested quantity
            #
            # This is the important part for preventing
            # concurrent orders from overselling stock.
            # ---------------------------------------------

            stock_stmt = (
                update(Product)
                .where(
                    Product.id == product.id,
                    Product.stock >= cart_item.quantity
                )
                .values(
                    stock=Product.stock - cart_item.quantity
                )
            )

            stock_result = await db.execute(
                stock_stmt
            )

            # ---------------------------------------------
            # Stock update failed
            # ---------------------------------------------
            #
            # rowcount == 0 means the UPDATE could not
            # happen.
            #
            # Usually this means insufficient stock.
            # ---------------------------------------------

            if stock_result.rowcount == 0:

                # Re-read the product to give the user
                # the actual available stock.

                check_stmt = (
                    select(Product)
                    .where(
                        Product.id == product.id
                    )
                )

                check_result = await db.execute(
                    check_stmt
                )

                current_product = (
                    check_result.scalar_one_or_none()
                )

                if current_product is None:

                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Product {product.id} "
                            "not found"
                        )
                    )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Insufficient stock for "
                        f"product '{current_product.name}'. "
                        f"Available stock: "
                        f"{current_product.stock}"
                    )
                )

            # ---------------------------------------------
            # Find product owner
            # ---------------------------------------------
            #
            # Seller-owned product:
            # seller_products contains the product.
            #
            # Admin-owned product:
            # no seller_products entry exists.
            # ---------------------------------------------

            seller_stmt = (
                select(SellerProduct)
                .where(
                    SellerProduct.product_id == product.id
                )
                .limit(1)
            )

            seller_result = await db.execute(
                seller_stmt
            )

            seller_product = (
                seller_result.scalar_one_or_none()
            )

            # ---------------------------------------------
            # Seller owns the product
            # ---------------------------------------------

            if seller_product is not None:

                owner_id = seller_product.seller_id

            # ---------------------------------------------
            # Otherwise product belongs to admin
            # ---------------------------------------------

            else:

                admin_stmt = (
                    select(User)
                    .where(
                        User.role == "ADMIN",
                        User.status == "ACTIVE"
                    )
                    .limit(1)
                )

                admin_result = await db.execute(
                    admin_stmt
                )

                admin_user = (
                    admin_result.scalar_one_or_none()
                )

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

        # -------------------------------------------------
        # Clear the cart
        # -------------------------------------------------

        for cart_item in cart.items:

            await db.delete(cart_item)

        # -------------------------------------------------
        # Commit everything together
        # -------------------------------------------------
        #
        # Order
        # OrderItems
        # Stock reduction
        # Cart deletion
        #
        # are committed together.
        #
        # If an error occurs before commit, rollback
        # prevents a partial order.
        # -------------------------------------------------

        await db.commit()

        # -------------------------------------------------
        # Reload order with items
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

        result = await db.execute(
            order_stmt
        )

        order = result.scalar_one()

        return order

    # -----------------------------------------------------
    # Application errors
    # -----------------------------------------------------

    except HTTPException:

        await db.rollback()

        raise

    # -----------------------------------------------------
    # Database errors
    # -----------------------------------------------------

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
        # -------------------------------------------------

        if order.status not in ("PENDING_PAYMENT", "CONFIRMED"):

            raise HTTPException(
                status_code=400,
                detail=(
                     "Only pending or confirmed "
                     "orders can be cancelled"
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

        # -------------------------------------------------
        # Handle payment refund based on payment_status
        # -------------------------------------------------
        #
        # PAID → initiate refund → REFUNDED
        # UNPAID / FAILED → no refund needed
        # COD → no refund (customer never paid online)
        # -------------------------------------------------

        if order.payment_status == "PAID":

            # -----------------------------------------
            # Find the successful payment record
            # -----------------------------------------

            payment_stmt = (
                select(Payment)
                .where(
                    Payment.order_id == order.id,
                    Payment.status == "SUCCESS"
                )
                .order_by(
                    Payment.created_at.desc()
                )
                .limit(1)
            )

            payment_result = await db.execute(
                payment_stmt
            )

            payment = payment_result.scalar_one_or_none()

            if payment is not None:

                # -------------------------------------
                # Simulate refund
                #
                # Later replace with:
                # razorpay_client.payment.refund(
                #     payment.gateway_payment_id,
                #     {"amount": int(payment.amount * 100)}
                # )
                # -------------------------------------

                payment.status = "REFUNDED"
                payment.gateway_status = "refunded"

            # -----------------------------------------
            # Update order payment status
            # -----------------------------------------

            order.payment_status = "REFUNDED"

        # -------------------------------------------------
        # Commit everything
        # -------------------------------------------------

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