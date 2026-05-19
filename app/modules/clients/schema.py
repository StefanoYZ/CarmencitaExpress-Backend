from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ClientCreate(BaseModel):
    document_type: Literal["DNI", "RUC"] = Field(alias="tipo_documento")
    document_number: str = Field(alias="numero_documento")
    legal_name: str = Field(alias="nombre_razon_social")
    address: str | None = Field(default=None, alias="direccion")
    phone: str | None = Field(default=None, alias="telefono")

    @field_validator("document_number")
    @classmethod
    def document_number_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("document_number cannot be empty")
        return value.strip()


class ClientResponse(BaseModel):
    id: int
    document_type: str = Field(alias="tipo_documento")
    document_number: str = Field(alias="numero_documento")
    legal_name: str = Field(alias="nombre_razon_social")
    address: str | None = Field(default=None, alias="direccion")
    phone: str | None = Field(default=None, alias="telefono")
