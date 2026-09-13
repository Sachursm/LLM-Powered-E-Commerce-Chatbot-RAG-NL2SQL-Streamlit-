from datetime import datetime

from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database.database import Base


class OTP(Base):
    __tablename__ = "otps"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    email: Mapped[str] = mapped_column(
        String(100),
        index=True
    )

    otp_code: Mapped[str] = mapped_column(
        String(6)
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )