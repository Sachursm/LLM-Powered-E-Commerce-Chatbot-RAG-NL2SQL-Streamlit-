from fastapi import (
    APIRouter, Depends, HTTPException, Request, status
)

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.dependencies import get_db

from app.database.models.user import User
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.product import Product
from app.database.models.review import Review

from app.schemas.review import (
    ReviewCreate,
    ReviewUpdate,
    ReviewResponse
)

from app.core.security import require_active_user
from app.core.rate_limit import limiter, get_user_key


router = APIRouter(
    tags=["Reviews"]
)


# =========================================================
# CREATE REVIEW
# =========================================================

@router.post(
    "/orders/{order_id}/items/{item_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED
)
@limiter.limit("5/minute", key_func=get_user_key)
async def create_review(
    request: Request,
    order_id: int,
    item_id: int,
    review_data: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        # -------------------------------------------------
        # Verify order belongs to customer
        # -------------------------------------------------

        order_stmt = (
            select(Order)
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id
            )
        )

        order_result = await db.execute(order_stmt)

        order = order_result.scalar_one_or_none()

        if order is None:

            raise HTTPException(
                status_code=404,
                detail="Order not found"
            )

        # -------------------------------------------------
        # Order must be delivered
        # -------------------------------------------------

        if order.status != "DELIVERED":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Reviews can only be submitted "
                    "for delivered orders"
                )
            )

        # -------------------------------------------------
        # Verify order item
        # -------------------------------------------------

        item_stmt = (
            select(OrderItem)
            .where(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id
            )
        )

        item_result = await db.execute(item_stmt)

        order_item = item_result.scalar_one_or_none()

        if order_item is None:

            raise HTTPException(
                status_code=404,
                detail="Order item not found"
            )

        # -------------------------------------------------
        # Validate rating
        # -------------------------------------------------

        if review_data.rating < 1 or (
            review_data.rating > 5
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Rating must be between 1 and 5"
                )
            )

        # -------------------------------------------------
        # Check if already reviewed
        # -------------------------------------------------

        existing_stmt = (
            select(Review)
            .where(
                Review.user_id == current_user.id,
                Review.product_id == (
                    order_item.product_id
                )
            )
        )

        existing_result = await db.execute(
            existing_stmt
        )

        if existing_result.scalar_one_or_none():

            raise HTTPException(
                status_code=400,
                detail=(
                    "You have already reviewed "
                    "this product"
                )
            )

        # -------------------------------------------------
        # Create review
        # -------------------------------------------------

        review = Review(
            user_id=current_user.id,
            product_id=order_item.product_id,
            order_item_id=order_item.id,
            rating=review_data.rating,
            review_text=review_data.review_text
        )

        db.add(review)

        await db.flush()

        # -------------------------------------------------
        # Update product rating
        # -------------------------------------------------

        await _update_product_rating(
            db, order_item.product_id
        )

        await db.commit()

        await db.refresh(review)

        return review

    except HTTPException:

        await db.rollback()

        raise

    except IntegrityError:

        await db.rollback()

        raise HTTPException(
            status_code=400,
            detail=(
                "You have already reviewed "
                "this product"
            )
        )

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# GET PRODUCT REVIEWS
# =========================================================

@router.get(
    "/products/{product_id}/reviews"
)
@limiter.limit("30/minute", key_func=get_user_key)
async def get_product_reviews(
    request: Request,
    product_id: int,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):

    try:

        product_stmt = (
            select(Product)
            .where(Product.id == product_id)
        )

        product_result = await db.execute(
            product_stmt
        )

        product = product_result.scalar_one_or_none()

        if product is None:

            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        # Count
        count_stmt = (
            select(func.count(Review.id))
            .where(
                Review.product_id == product_id
            )
        )

        count_result = await db.execute(count_stmt)

        total = count_result.scalar()

        # Query with pagination
        stmt = (
            select(Review, User.username)
            .join(
                User,
                User.id == Review.user_id
            )
            .where(
                Review.product_id == product_id
            )
            .order_by(
                Review.created_at.desc()
            )
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(stmt)

        rows = result.all()

        reviews = [
            {
                "id": review.id,
                "user_id": review.user_id,
                "username": username,
                "rating": review.rating,
                "review_text": review.review_text,
                "created_at": (
                    review.created_at.isoformat()
                )
            }
            for review, username in rows
        ]

        return {
            "product_id": product.id,
            "product_name": product.name,
            "average_rating": product.rating,
            "total_reviews": total,
            "reviews": {
                "items": reviews,
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": (skip + limit) < total
            }
        }

    except HTTPException:

        raise

    except SQLAlchemyError as e:

        print(f"DB ERROR: {e}")

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )

# =========================================================
# UPDATE MY REVIEW
# =========================================================

@router.patch(
    "/reviews/{review_id}",
    response_model=ReviewResponse
)
async def update_review(
    review_id: int,
    review_data: ReviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Review)
            .where(
                Review.id == review_id,
                Review.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        review = result.scalar_one_or_none()

        if review is None:

            raise HTTPException(
                status_code=404,
                detail="Review not found"
            )

        update_data = review_data.model_dump(
            exclude_unset=True
        )

        if not update_data:

            raise HTTPException(
                status_code=400,
                detail=(
                    "No fields provided for update"
                )
            )

        if "rating" in update_data:

            if update_data["rating"] < 1 or (
                update_data["rating"] > 5
            ):

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Rating must be between "
                        "1 and 5"
                    )
                )

        for field, value in update_data.items():
            setattr(review, field, value)

        await _update_product_rating(
            db, review.product_id
        )

        await db.commit()

        await db.refresh(review)

        return review

    except HTTPException:

        await db.rollback()

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# DELETE MY REVIEW
# =========================================================

@router.delete(
    "/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_review(
    review_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_user)
):

    try:

        stmt = (
            select(Review)
            .where(
                Review.id == review_id,
                Review.user_id == current_user.id
            )
        )

        result = await db.execute(stmt)

        review = result.scalar_one_or_none()

        if review is None:

            raise HTTPException(
                status_code=404,
                detail="Review not found"
            )

        product_id = review.product_id

        await db.delete(review)

        await _update_product_rating(
            db, product_id
        )

        await db.commit()

    except HTTPException:

        await db.rollback()

        raise

    except SQLAlchemyError:

        await db.rollback()

        raise HTTPException(
            status_code=503,
            detail=(
                "Database service temporarily "
                "unavailable"
            )
        )


# =========================================================
# HELPER: Update product rating
# =========================================================

async def _update_product_rating(
    db: AsyncSession,
    product_id: int
):

    stats_stmt = (
        select(
            func.avg(Review.rating),
            func.count(Review.id)
        )
        .where(
            Review.product_id == product_id
        )
    )

    stats_result = await db.execute(stats_stmt)

    avg_rating, count = stats_result.one()

    product_stmt = (
        select(Product)
        .where(Product.id == product_id)
    )

    product_result = await db.execute(product_stmt)

    product = product_result.scalar_one_or_none()
    if product is not None:

        if avg_rating is not None:
            product.rating = round(float(avg_rating), 2)
        else:
            product.rating = None  # type: ignore

        product.ratings_count = count if count else 0
