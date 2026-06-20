from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class Destination(Base):
    __tablename__ = "destinos"

    id = Column(Integer, primary_key=True, index=True)
    name = Column("nombre", String(120), nullable=False)
    normalized_name = Column(
        "nombre_normalizado",
        String(120),
        unique=True,
        index=True,
        nullable=False,
    )
    is_active = Column("activo", Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
