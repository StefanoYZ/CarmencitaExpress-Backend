from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base


class ChargeLog(Base):
    __tablename__ = "logs_de_cobro"

    id = Column(Integer, primary_key=True, index=True)
    observation_number = Column("numero_observacion", Integer, nullable=False)
    started_at = Column("timestamp_inicio", DateTime(timezone=True), nullable=False)
    finished_at = Column("timestamp_fin", DateTime(timezone=True), nullable=False)
    user = Column("usuario", String(120), nullable=True)
    response_time_ms = Column("tiempo_respuesta_ms", Integer, nullable=False)
    result = Column("resultado", String(20), nullable=False)
    modality = Column("modalidad", String(80), nullable=False)
    created_at = Column(
        "fecha_creacion",
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
