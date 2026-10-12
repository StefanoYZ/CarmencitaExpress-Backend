from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.modules.destinations.model import Destination  # noqa: F401


class Agency(Base):
    __tablename__ = "agencias"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, index=True, nullable=False)
    destination_id = Column(Integer, ForeignKey("destinos.id"), unique=True, index=True, nullable=False)
    address = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    destination = relationship("Destination")
