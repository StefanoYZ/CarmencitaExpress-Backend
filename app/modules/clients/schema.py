from datetime import datetime
import re

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ClientBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")

    document_type: str | None = Field(default="DNI", validation_alias=AliasChoices("tipo_documento", "document_type"))
    dni: str = Field(validation_alias=AliasChoices("dni", "numero_documento"))
    full_name: str = Field(validation_alias=AliasChoices("nombre_completo", "nombre_razon_social"))
    phone: str | None = Field(default=None, validation_alias=AliasChoices("telefono", "phone"))
    email: str | None = Field(default=None, validation_alias=AliasChoices("correo", "email"))
    address: str | None = Field(default=None, validation_alias=AliasChoices("direccion", "address"))

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, value: str | None) -> str:
        document_type = value.strip().upper() if value else "DNI"
        if document_type != "DNI":
            raise ValueError("tipo_documento must be DNI for local clientes")
        return document_type

    @field_validator("dni")
    @classmethod
    def validate_dni(cls, value: str) -> str:
        dni = value.strip() if value else ""
        if not dni.isdigit():
            raise ValueError("dni must contain only numbers")
        if len(dni) != 8:
            raise ValueError("dni must have exactly 8 digits")
        return dni

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        name = _normalize_spaces(value)
        if not name:
            raise ValueError("nombre_completo cannot be empty")
        return name

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        phone = _optional_text(value)
        if phone is None:
            return None
        if not phone.isdigit():
            raise ValueError("telefono must contain only numbers")
        if len(phone) != 9:
            raise ValueError("telefono must have exactly 9 digits")
        if not phone.startswith("9"):
            raise ValueError("telefono must start with 9")
        if len(set(phone)) == 1:
            raise ValueError("telefono cannot repeat the same digit 9 times")
        return phone

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        email = _optional_text(value)
        if email is None:
            return None
        email = email.lower()
        if not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("correo must be valid")
        return email

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str | None) -> str | None:
        return _optional_normalized_text(value)


class ClientCreate(ClientBase):
    pass


class ClientUpsert(ClientBase):
    pass


class ClientUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    full_name: str | None = Field(default=None, validation_alias=AliasChoices("nombre_completo", "nombre_razon_social"))
    phone: str | None = Field(default=None, validation_alias=AliasChoices("telefono", "phone"))
    email: str | None = Field(default=None, validation_alias=AliasChoices("correo", "email"))
    address: str | None = Field(default=None, validation_alias=AliasChoices("direccion", "address"))

    @field_validator("full_name")
    @classmethod
    def validate_optional_full_name(cls, value: str | None) -> str | None:
        return _optional_normalized_text(value)

    @field_validator("phone")
    @classmethod
    def validate_optional_phone(cls, value: str | None) -> str | None:
        phone = _optional_text(value)
        if phone is None:
            return None
        if not phone.isdigit():
            raise ValueError("telefono must contain only numbers")
        if len(phone) != 9:
            raise ValueError("telefono must have exactly 9 digits")
        if not phone.startswith("9"):
            raise ValueError("telefono must start with 9")
        if len(set(phone)) == 1:
            raise ValueError("telefono cannot repeat the same digit 9 times")
        return phone

    @field_validator("email")
    @classmethod
    def validate_optional_email(cls, value: str | None) -> str | None:
        email = _optional_text(value)
        if email is None:
            return None
        email = email.lower()
        if not EMAIL_PATTERN.fullmatch(email):
            raise ValueError("correo must be valid")
        return email

    @field_validator("address")
    @classmethod
    def normalize_optional_address(cls, value: str | None) -> str | None:
        return _optional_normalized_text(value)


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    dni: str
    full_name: str = Field(serialization_alias="nombre_completo")
    phone: str | None = Field(default=None, serialization_alias="telefono")
    email: str | None = Field(default=None, serialization_alias="correo")
    address: str | None = Field(default=None, serialization_alias="direccion")
    created_at: datetime
    updated_at: datetime


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_spaces(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def _optional_normalized_text(value: str | None) -> str | None:
    normalized = _normalize_spaces(value)
    return normalized or None
