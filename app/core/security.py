from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import jwt
from pwdlib import PasswordHash

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.dependencies import get_db
from app.database.models.user import User


password_hash = PasswordHash.recommended()


# =========================================================
# PASSWORD
# =========================================================

def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:
    return password_hash.verify(
        plain_password,
        hashed_password
    )


# =========================================================
# JWT
# =========================================================

def create_access_token(
    user_id: int,
    role: str
) -> str:

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:

    try:

        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        return payload

    except jwt.ExpiredSignatureError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )

    except jwt.InvalidTokenError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


# =========================================================
# AUTHENTICATION
# =========================================================

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        bearer_scheme
    ),
    db: AsyncSession = Depends(get_db)
) -> User:

    token = credentials.credentials

    # Decode JWT
    payload = decode_access_token(token)

    user_id = payload.get("sub")

    if user_id is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    # Convert user ID from JWT string to integer
    try:

        user_id = int(user_id)

    except (TypeError, ValueError):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    # Find user
    stmt = select(User).where(
        User.id == user_id
    )

    result = await db.execute(stmt)

    user = result.scalar_one_or_none()

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


# =========================================================
# ACTIVE USER
# =========================================================

def require_active_user(
    current_user: User = Depends(get_current_user)
) -> User:

    if current_user.status != "ACTIVE":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    return current_user


# =========================================================
# ADMIN
# =========================================================

def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:

    if current_user.status != "ACTIVE":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    if current_user.role != "ADMIN":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    return current_user


# =========================================================
# ADMIN OR SELLER
# =========================================================

def require_admin_or_seller(
    current_user: User = Depends(get_current_user)
) -> User:

    if current_user.status != "ACTIVE":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    if current_user.role not in ["ADMIN", "SELLER"]:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or seller access required"
        )

    return current_user


# =========================================================
# SELLER
# =========================================================

def require_seller(
    current_user: User = Depends(get_current_user)
) -> User:

    if current_user.status != "ACTIVE":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    if current_user.role != "SELLER":

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seller access required"
        )

    return current_user