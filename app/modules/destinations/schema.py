import re
import unicodedata
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DestinationCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(alias="nombre", min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = normalize_destination_name(value)
        if len(normalized) < 2:
            raise ValueError("nombre must have at least 2 characters")
        return normalized


class DestinationUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = Field(default=None, alias="nombre", min_length=2, max_length=120)
    is_active: bool | None = Field(default=None, alias="activo")

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_destination_name(value)
        if len(normalized) < 2:
            raise ValueError("nombre must have at least 2 characters")
        return normalized


class DestinationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str = Field(serialization_alias="nombre")
    is_active: bool = Field(serialization_alias="activo")
    created_at: datetime
    updated_at: datetime


def normalize_destination_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_destination_key(value: str) -> str:
    text = normalize_destination_name(value).lower()
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(character)
    )
    return without_accents
