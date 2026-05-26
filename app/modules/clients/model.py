from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.core.database import Base


class Client(Base):
    __tablename__ = "clientes"

    dni = Column(String(8), primary_key=True, index=True)
    full_name = Column("nombre_completo", String(150), nullable=False)
    phone = Column("telefono", String(9), nullable=True)
    email = Column("correo", String(120), nullable=True)
    address = Column("direccion", String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
