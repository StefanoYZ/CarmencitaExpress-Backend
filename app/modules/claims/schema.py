from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CLAIM_CATEGORIES = {"DANO", "PERDIDA", "FALTANTE", "RETRASO", "ENTREGA", "COBRO", "ATENCION", "OTRO"}
CLAIM_STATUSES = {
    "RECIBIDO", "EN_REVISION", "ESPERANDO_INFORMACION", "INVESTIGANDO",
    "PROPUESTA_ENVIADA", "PAGO_POR_VERIFICAR", "RESUELTO", "NO_PROCEDE", "CERRADO",
}
CLAIM_NOTICE_VERSION = "2026-10-11"
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class PublicAgencyContact(BaseModel):
    id: int
    code: str
    place: str
    phone: str | None = None
    address: str | None = None


class ClaimPrivacyNotice(BaseModel):
    version: str
    text: str
    company_name: str
    company_ruc: str
    company_address: str | None = None
    contact_email: str | None = None


class PublicClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_code: str = Field(min_length=8, max_length=24)
    document_number: str = Field(min_length=8, max_length=20)
    agency_id: int = Field(gt=0)
    category: str
    description: str = Field(min_length=10, max_length=4000)
    requested_solution: str | None = Field(default=None, max_length=2000)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=160)
    privacy_notice_accepted: bool
    privacy_notice_version: str

    @field_validator("shipment_code")
    @classmethod
    def normalize_shipment_code(cls, value: str) -> str:
        return re.sub(r"\s+", "", value).upper()

    @field_validator("document_number")
    @classmethod
    def normalize_document_number(cls, value: str) -> str:
        return value.strip()

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in CLAIM_CATEGORIES:
            raise ValueError("Selecciona una categoría válida")
        return value

    @model_validator(mode="after")
    def validate_privacy_notice(self):
        if not self.privacy_notice_accepted or self.privacy_notice_version != CLAIM_NOTICE_VERSION:
            raise ValueError("Debes leer y aceptar el aviso vigente de privacidad")
        return self


class InPersonClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_code: str = Field(min_length=8, max_length=24)
    agency_id: int | None = Field(default=None, gt=0)
    claimant_document_number: str = Field(min_length=8, max_length=20)
    category: str
    description: str = Field(min_length=10, max_length=4000)
    requested_solution: str | None = Field(default=None, max_length=2000)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=160)
    privacy_notice_acknowledged: bool

    @model_validator(mode="after")
    def validate_privacy_notice(self):
        if not self.privacy_notice_acknowledged:
            raise ValueError("Confirma que se informó al cliente sobre el tratamiento de sus datos")
        return self


class InPersonClaimShipmentLookupResponse(BaseModel):
    shipment_code: str
    sender_document_type: str
    sender_document_number: str


class ClaimStatusLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_code: str | None = Field(default=None, min_length=8, max_length=32)
    shipment_code: str | None = Field(default=None, min_length=8, max_length=24)
    document_number: str | None = Field(default=None, min_length=8, max_length=20)

    @field_validator("case_code", "shipment_code")
    @classmethod
    def normalize_lookup_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return re.sub(r"\s+", "", value).upper()

    @field_validator("document_number")
    @classmethod
    def normalize_lookup_document(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_lookup_identifier(self):
        if not any((self.case_code, self.shipment_code, self.document_number)):
            raise ValueError("Ingresa un código de caso, código de encomienda o DNI")
        return self


class ClaimEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    note: str
    actor_name: str | None
    created_at: datetime


class PublicClaimEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    note: str
    created_at: datetime


class ShipmentTraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str = Field(serialization_alias="evento")
    status: str | None = Field(serialization_alias="estado")
    location: str | None = Field(serialization_alias="lugar")
    description: str = Field(serialization_alias="detalle")
    actor_name: str | None = None
    created_at: datetime = Field(serialization_alias="fecha")


class PublicShipmentTraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str = Field(serialization_alias="evento")
    status: str | None = Field(serialization_alias="estado")
    location: str | None = Field(serialization_alias="lugar")
    description: str = Field(serialization_alias="detalle")
    created_at: datetime = Field(serialization_alias="fecha")


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_code: str
    shipment_id: int
    agency_id: int
    source: str
    kind: str
    category: str
    claimant_role: str
    claimant_name: str
    claimant_document_number: str
    contact_phone: str | None
    contact_email: str | None
    description: str
    requested_solution: str | None
    status: str
    resolution_type: str | None
    resolution_text: str | None
    resolution_amount: float | None
    resolution_currency: str | None
    payment_method: str | None
    payment_reference: str | None
    payment_verified_by_id: int | None
    payment_verified_at: datetime | None
    payment_verified_by_name: str | None
    assigned_user_id: int | None
    resolution_recorded_by_user_id: int | None
    resolution_recorded_by_name: str | None
    resolved_by_user_id: int | None
    resolved_by_name: str | None
    created_at: datetime
    updated_at: datetime


class ClaimDetailResponse(BaseModel):
    claim: ClaimResponse
    shipment: ClaimShipmentSummary
    events: list[ClaimEventResponse]
    shipment_events: list[ShipmentTraceResponse]
    attachments: list[ClaimAttachmentResponse]


class PublicClaimCreateResponse(BaseModel):
    case_code: str
    status: str
    message: str


class PublicClaimStatusResponse(BaseModel):
    case_code: str
    category: str
    description: str
    requested_solution: str | None
    status: str
    created_at: datetime
    resolution_text: str | None
    events: list[PublicClaimEventResponse]


class ClaimEventCreate(BaseModel):
    event_type: Literal["NOTA", "ASIGNACION", "CONTACTO_CLIENTE", "INVESTIGACION"] = "NOTA"
    note: str = Field(min_length=3, max_length=4000)
    visible_to_customer: bool = False
    to_status: Literal[
        "RECIBIDO", "EN_REVISION", "ESPERANDO_INFORMACION", "INVESTIGANDO",
        "PROPUESTA_ENVIADA", "PAGO_POR_VERIFICAR", "RESUELTO", "NO_PROCEDE", "CERRADO",
    ] | None = None


class ClaimResolutionCreate(BaseModel):
    resolution_type: Literal["MONETARIA", "NO_MONETARIA"]
    resolution_text: str = Field(min_length=10, max_length=4000)
    amount: float | None = Field(default=None, gt=0, le=100000)
    currency: Literal["PEN"] = "PEN"
    payment_method: Literal["TRANSFERENCIA", "YAPE", "PLIN", "EFECTIVO", "OTRO"] | None = None
    payment_reference: str | None = Field(default=None, max_length=100)
    payment_proof_attachment_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_payment_resolution(self):
        if self.resolution_type == "MONETARIA" and not all((self.amount, self.payment_method, self.payment_proof_attachment_id)):
            raise ValueError("La solución monetaria requiere monto, medio de pago y comprobante")
        if self.resolution_type == "NO_MONETARIA" and any((self.amount, self.payment_method, self.payment_proof_attachment_id)):
            raise ValueError("Una solución no monetaria no debe incluir datos de pago")
        return self


class ClaimPaymentVerification(BaseModel):
    verified: bool
    note: str = Field(default="", max_length=2000)


class ClaimAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    attachment_kind: str
    file_name: str
    content_type: str
    file_size: int
    visible_to_customer: bool
    created_at: datetime


class ClaimShipmentSummary(BaseModel):
    id: int
    shipment_code: str
    origin: str
    destination: str
    status: str
    created_at: datetime


class ShipmentTraceCreate(BaseModel):
    event_type: Literal["RECOGIDA", "SALIDA_AGENCIA", "EN_TRANSITO", "LLEGADA_AGENCIA", "INCIDENCIA", "OTRO"]
    location: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=3, max_length=2000)
    status: str | None = Field(default=None, max_length=30)
    visible_to_customer: bool = True
