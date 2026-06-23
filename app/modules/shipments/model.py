from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.core.business_time import business_now
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
    content_type = Column("tipo_contenido", String(50), nullable=True)
    base_orientation = Column("orientacion_base", String(30), nullable=True)
    registration_origin = Column("origen_registro", String(20), nullable=True)
    status = Column("estado", String(30), nullable=False)
    cancellation_reason = Column("motivo_anulacion", Text, nullable=True)
    canceled_at = Column("fecha_anulacion", DateTime(timezone=True), nullable=True)
    delivered_at = Column("fecha_entrega", DateTime(timezone=True), nullable=True)
    delivery_receiver_document = Column("dni_receptor_entrega", String(20), nullable=True)
    digital_signature_base64 = Column("firma_digital_base64", Text, nullable=True)
    security_key = Column("clave_seguridad", String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), default=business_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=business_now,
        onupdate=business_now,
        nullable=False,
    )
