from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


FRAGILITY_VALUES = {"BAJA", "MEDIA", "ALTA"}
SHIPMENT_STATUS_VALUES = {
    "REGISTRADA",
    "COTIZADA",
    "PAGO_CONFIRMADO",
    "BOLETA_EMITIDA",
    "EN_TRANSITO",
    "ENTREGADA",
    "ANULADA",
}


class ShipmentCreate(BaseModel):
    sender_document_type: str = Field(alias="remitente_tipo_documento")
    sender_document_number: str = Field(alias="remitente_numero_documento")
    sender_name: str = Field(alias="remitente_nombre")
    sender_address: str | None = Field(default=None, alias="remitente_direccion")
    sender_phone: str | None = Field(default=None, alias="remitente_telefono")

    recipient_document_type: str | None = Field(default=None, alias="destinatario_tipo_documento")
    recipient_document_number: str | None = Field(default=None, alias="destinatario_numero_documento")
    recipient_name: str = Field(alias="destinatario_nombre")
    recipient_address: str | None = Field(default=None, alias="destinatario_direccion")
    recipient_phone: str | None = Field(default=None, alias="destinatario_telefono")

    origin: str = Field(default="Trujillo", alias="origen")
    destination: str = Field(alias="destino")
    description: str = Field(alias="descripcion")
    weight_kg: float = Field(alias="peso_kg")
    length_cm: float = Field(alias="largo_cm")
    width_cm: float = Field(alias="ancho_cm")
    height_cm: float = Field(alias="alto_cm")
    fragility: str = Field(alias="fragilidad")

    @field_validator("sender_document_number", "sender_name", "recipient_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("The field cannot be empty")
        return value.strip()

    @field_validator("origin", "destination")
    @classmethod
    def normalize_route(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("origin and destination cannot be empty")
        return value.strip()

    @field_validator("weight_kg", "length_cm", "width_cm", "height_cm")
    @classmethod
    def dimensions_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("weight_kg, length_cm, width_cm and height_cm must be greater than 0")
        return value

    @field_validator("fragility")
    @classmethod
    def normalize_fragility(cls, value: str) -> str:
        fragility = value.strip().upper() if value else ""
        if fragility not in FRAGILITY_VALUES:
            raise ValueError("fragility must be BAJA, MEDIA or ALTA")
        return fragility


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    shipment_code: str = Field(alias="codigo_encomienda")

    sender_document_type: str = Field(alias="remitente_tipo_documento")
    sender_document_number: str = Field(alias="remitente_numero_documento")
    sender_name: str = Field(alias="remitente_nombre")
    sender_address: str | None = Field(default=None, alias="remitente_direccion")
    sender_phone: str | None = Field(default=None, alias="remitente_telefono")

    recipient_document_type: str | None = Field(default=None, alias="destinatario_tipo_documento")
    recipient_document_number: str | None = Field(default=None, alias="destinatario_numero_documento")
    recipient_name: str = Field(alias="destinatario_nombre")
    recipient_address: str | None = Field(default=None, alias="destinatario_direccion")
    recipient_phone: str | None = Field(default=None, alias="destinatario_telefono")

    origin: str = Field(alias="origen")
    destination: str = Field(alias="destino")
    description: str = Field(alias="descripcion")
    weight_kg: float = Field(alias="peso_kg")
    length_cm: float = Field(alias="largo_cm")
    width_cm: float = Field(alias="ancho_cm")
    height_cm: float = Field(alias="alto_cm")
    fragility: str = Field(alias="fragilidad")
    status: str = Field(alias="estado")
    created_at: datetime = Field(alias="fecha_creacion")
    updated_at: datetime = Field(alias="fecha_actualizacion")


class ShipmentUpdate(BaseModel):
    sender_document_type: str = Field(alias="remitente_tipo_documento")
    sender_document_number: str = Field(alias="remitente_numero_documento")
    sender_name: str = Field(alias="remitente_nombre")
    sender_address: str | None = Field(default=None, alias="remitente_direccion")
    sender_phone: str | None = Field(default=None, alias="remitente_telefono")

    recipient_document_type: str | None = Field(default=None, alias="destinatario_tipo_documento")
    recipient_document_number: str | None = Field(default=None, alias="destinatario_numero_documento")
    recipient_name: str = Field(alias="destinatario_nombre")
    recipient_address: str | None = Field(default=None, alias="destinatario_direccion")
    recipient_phone: str | None = Field(default=None, alias="destinatario_telefono")

    origin: str = Field(alias="origen")
    destination: str = Field(alias="destino")
    description: str = Field(alias="descripcion")
    weight_kg: float = Field(alias="peso_kg")
    length_cm: float = Field(alias="largo_cm")
    width_cm: float = Field(alias="ancho_cm")
    height_cm: float = Field(alias="alto_cm")
    fragility: str = Field(alias="fragilidad")
    status: str = Field(alias="estado")

    @field_validator("sender_document_number", "sender_name", "recipient_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("The field cannot be empty")
        return value.strip()

    @field_validator("origin", "destination")
    @classmethod
    def normalize_route(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("origin and destination cannot be empty")
        return value.strip()

    @field_validator("weight_kg", "length_cm", "width_cm", "height_cm")
    @classmethod
    def dimensions_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("weight_kg, length_cm, width_cm and height_cm must be greater than 0")
        return value

    @field_validator("fragility")
    @classmethod
    def normalize_fragility(cls, value: str) -> str:
        fragility = value.strip().upper() if value else ""
        if fragility not in FRAGILITY_VALUES:
            raise ValueError("fragility must be BAJA, MEDIA or ALTA")
        return fragility

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        status = value.strip().upper() if value else ""
        if status not in SHIPMENT_STATUS_VALUES:
            raise ValueError("status must be one of the allowed shipment states")
        return status


class ShipmentDeleteResponse(BaseModel):
    success: bool
    message: str
    id: int
    shipment_code: str = Field(alias="codigo_encomienda")
    status: str = Field(alias="estado")
