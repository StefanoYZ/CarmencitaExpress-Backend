from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.users.schema import UserResponse


class AgencyDestinationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool


class AgencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: int = Field(gt=0)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("address", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AgencyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: int | None = Field(default=None, gt=0)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("destination_id")
    @classmethod
    def destination_cannot_be_null(cls, value: int | None) -> int | None:
        if value is None:
            raise ValueError("destination_id cannot be null")
        return value

    @field_validator("address", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AgencyUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1, max_length=150)
    role: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("username is required")
        return normalized

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("full_name is required")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.strip()) < 6:
            raise ValueError("password must contain at least 6 characters")
        return value

    @field_validator("role")
    @classmethod
    def validate_operational_role(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"SECRETARIA", "ESTIBA"}:
            raise ValueError("Solo se permiten los roles SECRETARIA y ESTIBA")
        return normalized


class AgencyAdminAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | None = Field(default=None, gt=0)
    username: str | None = Field(default=None, min_length=1, max_length=50)
    password: str | None = Field(default=None, min_length=6)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value else None

    @model_validator(mode="after")
    def require_existing_user_or_new_credentials(self):
        has_new_user = any(value is not None for value in (self.username, self.password, self.full_name))
        if self.user_id is not None and has_new_user:
            raise ValueError("Use user_id o los datos de un nuevo usuario, no ambos")
        if self.user_id is None and not all((self.username, self.password, self.full_name)):
            raise ValueError("Debe indicar user_id o username, password y full_name")
        return self


class AgencyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    code: str
    destination_id: int
    address: str | None
    phone: str | None
    is_active: bool
    destination: AgencyDestinationResponse
    admin: UserResponse | None = None
    created_at: datetime
    updated_at: datetime


class AgencyShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_code: str
    status: str
    origin: str
    destination: str
    recipient_name: str
    weight_kg: float
    created_at: datetime


class AgencyDashboardResponse(BaseModel):
    agency: AgencyResponse
    total_shipments: int
    active_shipments: int
    delivered_shipments: int
    canceled_shipments: int
    status_counts: dict[str, int]
    recent_shipments: list[AgencyShipmentResponse]
