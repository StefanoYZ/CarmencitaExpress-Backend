from typing import Literal

from pydantic import BaseModel, field_validator


class ClienteCreate(BaseModel):
    tipo_documento: Literal["DNI", "RUC"]
    numero_documento: str
    nombre_razon_social: str
    direccion: str | None = None
    telefono: str | None = None

    @field_validator("numero_documento")
    @classmethod
    def numero_documento_no_vacio(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("numero_documento no puede estar vacio")
        return value.strip()


class ClienteResponse(BaseModel):
    id: int
    tipo_documento: str
    numero_documento: str
    nombre_razon_social: str
    direccion: str | None = None
    telefono: str | None = None
