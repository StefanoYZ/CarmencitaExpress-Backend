from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer

from app.core.database import Base


class IntegrationSettings(Base):
    __tablename__ = "configuracion_integraciones"

    id = Column(Integer, primary_key=True, default=1)
    mercadopago_enabled = Column(Boolean, nullable=False, default=True)
    lycet_enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        "fecha_actualizacion",
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
