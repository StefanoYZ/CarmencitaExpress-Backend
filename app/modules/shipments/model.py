from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.database import Base


class Shipment(Base):
    __tablename__ = "encomiendas"

    id = Column(Integer, primary_key=True, index=True)
    shipment_code = Column("codigo_encomienda", String(20), unique=True, index=True, nullable=False)

    sender_document_type = Column("remitente_tipo_documento", String(20), nullable=False)
    sender_document_number = Column("remitente_numero_documento", String(20), nullable=False)
    sender_name = Column("remitente_nombre", String(150), nullable=False)
    sender_address = Column("remitente_direccion", String(255), nullable=True)
    sender_phone = Column("remitente_telefono", String(20), nullable=True)

    recipient_document_type = Column("destinatario_tipo_documento", String(20), nullable=True)
    recipient_document_number = Column("destinatario_numero_documento", String(20), nullable=True)
    recipient_name = Column("destinatario_nombre", String(150), nullable=False)
    recipient_address = Column("destinatario_direccion", String(255), nullable=True)
    recipient_phone = Column("destinatario_telefono", String(20), nullable=True)

    origin = Column("origen", String(100), nullable=False)
    destination = Column("destino", String(100), nullable=False)
    description = Column("descripcion", String(255), nullable=False)
    weight_kg = Column("peso_kg", Float, nullable=False)
    length_cm = Column("largo_cm", Float, nullable=False)
    width_cm = Column("ancho_cm", Float, nullable=False)
    height_cm = Column("alto_cm", Float, nullable=False)
    fragility = Column("fragilidad", String(20), nullable=False)
    status = Column("estado", String(30), nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
