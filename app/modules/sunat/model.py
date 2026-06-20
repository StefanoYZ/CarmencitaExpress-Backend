from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint

from app.core.database import Base


class ElectronicReceipt(Base):
    __tablename__ = "boletas_electronicas"
    __table_args__ = (
        UniqueConstraint("serie", "numero", name="uq_boleta_serie_numero"),
    )

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column("encomienda_id", Integer, unique=True, index=True, nullable=False)
    environment = Column("ambiente", String(20), nullable=False)
    status = Column("estado", String(40), nullable=False)
    series = Column("serie", String(10), nullable=False)
    number = Column("numero", String(20), nullable=False)
    issue_date = Column("fecha_emision", String(30), nullable=False)
    subtotal = Column(Float, nullable=False)
    igv = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    currency = Column("moneda", String(5), nullable=False, default="PEN")
    hash = Column(String(255), nullable=True)
    signed_xml = Column("xml_firmado", Text, nullable=True)
    cdr_zip = Column("cdr_zip", Text, nullable=True)
    cdr_code = Column("cdr_codigo", String(20), nullable=True)
    cdr_description = Column("cdr_descripcion", Text, nullable=True)
    cdr_notes = Column("cdr_notas", JSON, nullable=False, default=list)
    request_payload = Column("payload_enviado", JSON, nullable=False)
    raw_response = Column("respuesta_lycet", JSON, nullable=True)
    created_at = Column(
        "fecha_creacion",
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        "fecha_actualizacion",
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
