from datetime import datetime
import math
import re

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.shipments.constants import (
    FRAGILITY_VALUES,
    MAX_DIMENSION_CM,
    MAX_ENVELOPE_WEIGHT_KG,
    MAX_WEIGHT_KG,
    SHIPMENT_STATUS_VALUES,
)

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
BASE_ORIENTATION_VALUES = {"LARGO_ANCHO", "LARGO_ALTO", "ANCHO_ALTO"}
BASE_VERTICAL_DIMENSION = {
    "LARGO_ANCHO": "height",
    "LARGO_ALTO": "width",
    "ANCHO_ALTO": "length",
}
VERTICAL_ONLY_CONTENT_KEYWORDS = (
    "refrigeradora",
    "refrigerador",
    "refri",
    "congeladora",
    "congelador",
    "cocina",
    "microondas",
    "licuadora",
    "lavadora",
    "secadora",
    "air fryer",
    "freidora",
    "olla arrocera",
    "extractora",
    "electrodomestico",
    "electrodomesticos",
)


class ShipmentPayloadBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sender_document_type: str = Field(alias="remitente_tipo_documento")
    sender_document_number: str = Field(alias="remitente_numero_documento")
    sender_name: str = Field(alias="remitente_nombre")
    sender_address: str | None = Field(default=None, alias="remitente_direccion")
    sender_phone: str | None = Field(default=None, alias="remitente_telefono")
    sender_email: str | None = Field(default=None, alias="remitente_correo")

    recipient_document_type: str | None = Field(default=None, alias="destinatario_tipo_documento")
    recipient_document_number: str | None = Field(default=None, alias="destinatario_numero_documento")
    recipient_name: str = Field(alias="destinatario_nombre")
    recipient_address: str | None = Field(default=None, alias="destinatario_direccion")
    recipient_phone: str | None = Field(default=None, alias="destinatario_telefono")
    recipient_email: str | None = Field(default=None, alias="destinatario_correo")

    origin: str = Field(default="Trujillo", alias="origen")
    destination: str = Field(alias="destino")
    description: str = Field(alias="descripcion")
    content_type: str | None = Field(default=None, alias="tipo_contenido")
    weight_kg: float = Field(alias="peso_kg")
    length_cm: float = Field(alias="largo_cm")
    width_cm: float = Field(alias="ancho_cm")
    height_cm: float = Field(alias="alto_cm")
    fragility: str = Field(alias="fragilidad")
    base_orientation: str | None = Field(default=None, alias="orientacion_base")

    @field_validator("sender_document_type", "sender_document_number")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("The field cannot be empty")
        return value.strip()

    @field_validator("sender_name", "recipient_name", "description")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = _normalize_spaces(value)
        if not normalized:
            raise ValueError("The field cannot be empty")
        return normalized

    @field_validator("origin", "destination")
    @classmethod
    def normalize_route(cls, value: str) -> str:
        normalized = _normalize_spaces(value)
        if not normalized:
            raise ValueError("origin and destination cannot be empty")
        return normalized

    @field_validator(
        "sender_address",
        "sender_phone",
        "sender_email",
        "recipient_document_number",
        "recipient_address",
        "recipient_phone",
        "recipient_email",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("sender_address", "recipient_address")
    @classmethod
    def normalize_optional_address(cls, value: str | None) -> str | None:
        normalized = _normalize_spaces(value)
        return normalized or None

    @field_validator("sender_document_type", "recipient_document_type", "content_type")
    @classmethod
    def normalize_codes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized.upper() if normalized else None

    @field_validator("sender_phone", "recipient_phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isdigit():
            raise ValueError("phone must contain only numbers")
        if len(value) != 9:
            raise ValueError("phone must have exactly 9 digits")
        if not value.startswith("9"):
            raise ValueError("phone must start with 9")
        if len(set(value)) == 1:
            raise ValueError("phone cannot repeat the same digit 9 times")
        return value

    @field_validator("sender_email", "recipient_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("email must be valid")
        return email

    @field_validator("weight_kg")
    @classmethod
    def weight_must_be_positive(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("weight_kg must be greater than 0")
        if value > MAX_WEIGHT_KG:
            raise ValueError(f"weight_kg must not exceed {MAX_WEIGHT_KG:g} kg")
        return value

    @field_validator("length_cm", "width_cm", "height_cm")
    @classmethod
    def dimensions_must_be_non_negative(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("length_cm, width_cm and height_cm cannot be negative")
        if value > MAX_DIMENSION_CM:
            raise ValueError(f"dimensions must not exceed {MAX_DIMENSION_CM:g} cm")
        return value

    @field_validator("fragility")
    @classmethod
    def normalize_fragility(cls, value: str) -> str:
        fragility = value.strip().upper() if value else ""
        if fragility not in FRAGILITY_VALUES:
            raise ValueError("fragility must be BAJA, MEDIA or ALTA")
        return fragility

    @field_validator("content_type")
    @classmethod
    def normalize_content_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("tipo_contenido cannot be empty")
        return normalized

    @field_validator("base_orientation")
    @classmethod
    def normalize_base_orientation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in BASE_ORIENTATION_VALUES:
            raise ValueError(
                "orientacion_base must be LARGO_ANCHO, LARGO_ALTO or ANCHO_ALTO"
            )
        return normalized

    @model_validator(mode="after")
    def validate_document_numbers(self):
        _validate_document_number(self.sender_document_type, self.sender_document_number, "remitente_numero_documento")
        if self.recipient_document_number:
            _validate_document_number(
                self.recipient_document_type,
                self.recipient_document_number,
                "destinatario_numero_documento",
            )
        if self.origin.casefold() == self.destination.casefold():
            raise ValueError("origin and destination must be different")
        if self.content_type != "DOCUMENTOS" and any(
            dimension <= 0
            for dimension in (self.length_cm, self.width_cm, self.height_cm)
        ):
            raise ValueError("package dimensions must be greater than 0")
        if self.content_type != "DOCUMENTOS" and not self.base_orientation:
            raise ValueError("orientacion_base is required for packages")
        if self.content_type != "DOCUMENTOS" and not _base_orientation_is_safe(
            content_type=self.content_type,
            description=self.description,
            fragility=self.fragility,
            base_orientation=self.base_orientation,
            length_cm=self.length_cm,
            width_cm=self.width_cm,
            height_cm=self.height_cm,
        ):
            raise ValueError(
                "orientacion_base is not safe for this package; select the base that keeps it upright"
            )
        if self.content_type == "DOCUMENTOS":
            if self.weight_kg > MAX_ENVELOPE_WEIGHT_KG:
                raise ValueError(
                    f"un sobre (DOCUMENTOS) no puede pesar mas de {MAX_ENVELOPE_WEIGHT_KG:g} kg"
                )
            self.base_orientation = None
        return self

    @model_validator(mode="after")
    def validate_distinct_contact(self):
        # Regla de negocio: si remitente y destinatario son la MISMA persona
        # (mismo DNI), pueden compartir teléfono y correo. Si son personas
        # distintas (o el destinatario no se identifica con DNI), no se permite
        # que compartan el mismo teléfono ni el mismo correo.
        same_person = bool(
            self.sender_document_number
            and self.recipient_document_number
            and self.sender_document_number.strip() == self.recipient_document_number.strip()
        )
        if same_person:
            return self
        if self.sender_phone and self.recipient_phone and self.sender_phone == self.recipient_phone:
            raise ValueError(
                "sender and recipient cannot share the same phone unless they are the same person (same DNI)"
            )
        if self.sender_email and self.recipient_email and self.sender_email == self.recipient_email:
            raise ValueError(
                "sender and recipient cannot share the same email unless they are the same person (same DNI)"
            )
        return self


class ShipmentCreate(ShipmentPayloadBase):
    pass


class ShipmentPreRegistrationCreate(ShipmentPayloadBase):
    pass


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
    content_type: str | None = Field(default=None, alias="tipo_contenido")
    weight_kg: float = Field(alias="peso_kg")
    length_cm: float = Field(alias="largo_cm")
    width_cm: float = Field(alias="ancho_cm")
    height_cm: float = Field(alias="alto_cm")
    fragility: str = Field(alias="fragilidad")
    base_orientation: str | None = Field(default=None, alias="orientacion_base")
    registration_origin: str | None = Field(default=None, alias="origen_registro")
    status: str = Field(alias="estado")
    cancellation_reason: str | None = Field(default=None, alias="motivo_anulacion")
    canceled_at: datetime | None = Field(default=None, alias="fecha_anulacion")
    delivered_at: datetime | None = Field(default=None, alias="fecha_entrega")
    delivery_receiver_document: str | None = Field(default=None, alias="dni_receptor_entrega")
    digital_signature_base64: str | None = Field(default=None, alias="firma_digital_base64")
    security_key: str | None = Field(default=None, alias="clave_seguridad")
    created_at: datetime = Field(alias="fecha_creacion")
    updated_at: datetime = Field(alias="fecha_actualizacion")


class ShipmentUpdate(ShipmentPayloadBase):
    status: str | None = Field(default=None, alias="estado")

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        status = value.strip().upper() if value else ""
        if status not in SHIPMENT_STATUS_VALUES:
            raise ValueError("status must be one of the allowed shipment states")
        return status


class ShipmentPreRegistrationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    shipment_code: str = Field(alias="codigo_encomienda")
    status: str = Field(alias="estado")
    registration_origin: str = Field(alias="origen_registro")
    message: str = Field(alias="mensaje")


class ConfirmPreRegistrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_orientation: str | None = Field(default=None, alias="orientacion_base")

    @field_validator("base_orientation")
    @classmethod
    def normalize_base_orientation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            return None
        if normalized not in BASE_ORIENTATION_VALUES:
            raise ValueError(
                "orientacion_base must be LARGO_ANCHO, LARGO_ALTO or ANCHO_ALTO"
            )
        return normalized


class ShipmentCancelRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    reason: str = Field(alias="motivo")

    @field_validator("reason")
    @classmethod
    def reason_is_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("motivo is required")
        return value.strip()


class ShipmentDeleteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    message: str
    id: int
    shipment_code: str = Field(alias="codigo_encomienda")
    status: str = Field(alias="estado")
    cancellation_reason: str | None = Field(default=None, alias="motivo_anulacion")
    canceled_at: datetime | None = Field(default=None, alias="fecha_anulacion")
    charge_reversal: str = Field(default="PENDIENTE_NO_INTEGRADO", alias="reversion_cobro")


class LabelQrPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    shipment_code: str = Field(alias="codigo_encomienda")
    origin: str = Field(alias="origen")
    destination: str = Field(alias="destino")
    tracking: str


class ShipmentLabelResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    shipment_code: str = Field(alias="codigo_encomienda")
    origin: str = Field(alias="origen")
    destination: str = Field(alias="destino")
    sender: str = Field(alias="remitente")
    recipient: str = Field(alias="destinatario")
    qr_payload: LabelQrPayload


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    receiver_document: str = Field(
        validation_alias=AliasChoices("dni_receptor", "dni_receptor_entrega"),
        serialization_alias="dni_receptor",
    )
    security_key: str | None = Field(default=None, alias="clave_seguridad")
    signature_base64: str | None = Field(default=None, alias="firma_base64")

    @field_validator("receiver_document")
    @classmethod
    def receiver_document_is_required(cls, value: str) -> str:
        document = value.strip() if value else ""
        if not document:
            raise ValueError("dni_receptor is required")
        if not document.isdigit():
            raise ValueError("dni_receptor must contain only numbers")
        if len(document) != 8:
            raise ValueError("dni_receptor must have exactly 8 digits")
        return document

    @field_validator("security_key", "signature_base64")
    @classmethod
    def normalize_optional_delivery_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    message: str
    id: int
    shipment_code: str = Field(alias="codigo_encomienda")
    status: str = Field(alias="estado")
    delivered_at: datetime = Field(alias="fecha_entrega")
    receiver_document: str = Field(alias="dni_receptor_entrega")
    signature_saved: bool = Field(alias="firma_guardada")


def _validate_document_number(document_type: str | None, document_number: str | None, field_name: str) -> None:
    document_type = (document_type or "").strip().upper()
    document_number = (document_number or "").strip()
    if document_type != "DNI":
        return
    if not document_number.isdigit():
        raise ValueError(f"{field_name} must contain only numbers")
    if len(document_number) != 8:
        raise ValueError(f"{field_name} must have exactly 8 digits")


def _normalize_spaces(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def _base_orientation_is_safe(
    *,
    content_type: str | None,
    description: str | None,
    fragility: str | None,
    base_orientation: str | None,
    length_cm: float,
    width_cm: float,
    height_cm: float,
) -> bool:
    if not base_orientation:
        return False

    description_norm = _normalize_spaces(description).casefold()
    requires_upright = (
        (content_type or "").upper() == "ELECTRODOMESTICOS"
        or (fragility or "").upper() == "ALTA"
        or any(keyword in description_norm for keyword in VERTICAL_ONLY_CONTENT_KEYWORDS)
    )
    if not requires_upright:
        return True

    dimensions = {
        "length": float(length_cm),
        "width": float(width_cm),
        "height": float(height_cm),
    }
    vertical_key = BASE_VERTICAL_DIMENSION.get(base_orientation)
    vertical_value = dimensions.get(vertical_key or "", 0)
    largest_value = max(dimensions.values())
    return vertical_value >= largest_value / 1.3
