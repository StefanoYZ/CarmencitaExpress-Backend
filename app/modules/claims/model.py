from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Claim(Base):
    __tablename__ = "reclamos"

    id = Column(Integer, primary_key=True, index=True)
    case_code = Column(String(32), unique=True, index=True, nullable=False)
    shipment_id = Column(Integer, ForeignKey("encomiendas.id"), index=True, nullable=False)
    agency_id = Column(Integer, ForeignKey("agencias.id"), index=True, nullable=False)
    source = Column(String(20), nullable=False)  # WEB, PRESENCIAL, TELEFONO
    kind = Column(String(24), nullable=False, default="OPERATIVO")  # legacy values are retained for old cases
    formal_type = Column(String(16), nullable=True)  # retained only for historical records
    category = Column(String(40), nullable=False)
    claimant_role = Column(String(20), nullable=False)  # REMITENTE, DESTINATARIO
    claimant_name = Column(String(150), nullable=False)
    claimant_document_type = Column(String(20), nullable=False)
    claimant_document_number = Column(String(20), nullable=False)
    contact_phone = Column(String(30), nullable=True)
    contact_email = Column(String(160), nullable=True)
    description = Column(Text, nullable=False)
    requested_solution = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="RECIBIDO", index=True)
    assigned_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True, index=True)
    response_due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    privacy_notice_version = Column(String(40), nullable=True)
    privacy_notice_accepted_at = Column(DateTime(timezone=True), nullable=True)
    resolution_type = Column(String(20), nullable=True)
    resolution_text = Column(Text, nullable=True)
    resolution_amount = Column(Float, nullable=True)
    resolution_currency = Column(String(3), nullable=True, default="PEN")
    payment_method = Column(String(40), nullable=True)
    payment_reference = Column(String(100), nullable=True)
    payment_proof_attachment_id = Column(Integer, nullable=True)
    payment_verified_by_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True)
    payment_verified_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_recorded_by_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True, index=True)
    resolved_by_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    resolution_recorded_by = relationship("InternalUser", foreign_keys=[resolution_recorded_by_user_id])
    resolved_by = relationship("InternalUser", foreign_keys=[resolved_by_user_id])
    payment_verifier = relationship("InternalUser", foreign_keys=[payment_verified_by_id])

    @property
    def resolution_recorded_by_name(self) -> str | None:
        return self.resolution_recorded_by.full_name if self.resolution_recorded_by else None

    @property
    def resolved_by_name(self) -> str | None:
        return self.resolved_by.full_name if self.resolved_by else None

    @property
    def payment_verified_by_name(self) -> str | None:
        return self.payment_verifier.full_name if self.payment_verifier else None


class ClaimEvent(Base):
    __tablename__ = "reclamo_eventos"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("reclamos.id", ondelete="CASCADE"), index=True, nullable=False)
    actor_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True)
    event_type = Column(String(40), nullable=False)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)
    note = Column(Text, nullable=False)
    visible_to_customer = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    actor = relationship("InternalUser", foreign_keys=[actor_user_id])

    @property
    def actor_name(self) -> str | None:
        if self.actor is not None:
            return self.actor.full_name
        return "Cliente" if self.event_type == "RECIBIDO" else "Sistema"


class ClaimAttachment(Base):
    __tablename__ = "reclamo_adjuntos"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("reclamos.id", ondelete="CASCADE"), index=True, nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True)
    attachment_kind = Column(String(30), nullable=False)  # EVIDENCIA_CLIENTE, PAGO, OTRO
    file_name = Column(String(180), nullable=False)
    content_type = Column(String(40), nullable=False)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    data = Column(LargeBinary, nullable=False)
    visible_to_customer = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShipmentTraceEvent(Base):
    __tablename__ = "encomienda_eventos_trazabilidad"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("encomiendas.id", ondelete="CASCADE"), index=True, nullable=False)
    agency_id = Column(Integer, ForeignKey("agencias.id"), index=True, nullable=True)
    actor_user_id = Column(Integer, ForeignKey("internal_users.id"), nullable=True)
    event_type = Column(String(40), nullable=False)
    status = Column(String(30), nullable=True)
    location = Column(String(160), nullable=True)
    description = Column(Text, nullable=False)
    source = Column(String(20), nullable=False, default="SISTEMA")
    visible_to_customer = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    actor = relationship("InternalUser", foreign_keys=[actor_user_id])

    @property
    def actor_name(self) -> str | None:
        if self.actor is not None:
            return self.actor.full_name
        return {
            "SISTEMA": "Sistema",
            "WEB": "Cliente (web)",
            "PUBLIC_WEB": "Cliente (web)",
        }.get(self.source)
