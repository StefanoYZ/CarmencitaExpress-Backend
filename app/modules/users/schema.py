from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class PermissionBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    code: str
    name: str
    description: str | None = None
    module: str
    action: str

    @field_validator("code", "name", "module", "action")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("The field cannot be empty")
        return value.strip()

    @field_validator("code", "module", "action")
    @classmethod
    def normalize_code_parts(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    code: str | None = None
    name: str | None = None
    description: str | None = None
    module: str | None = None
    action: str | None = None

    @field_validator("code", "name", "module", "action")
    @classmethod
    def normalize_optional_required_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("The field cannot be empty")
        normalized = value.strip()
        if info.field_name in {"code", "module", "action"}:
            return normalized.lower()
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    code: str
    name: str
    description: str | None = None
    module: str
    action: str
    created_at: datetime
    updated_at: datetime


class RoleBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    description: str | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_role_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("name is required")
        return value.strip().upper()

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = None
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_role_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("name cannot be empty")
        return value.strip().upper()

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RoleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    description: str | None = None
    is_active: bool
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    username: str
    password: str
    full_name: str

    @field_validator("username", "password", "full_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("The field cannot be empty")
        return value.strip()

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.strip()) < 6:
            raise ValueError("password must contain at least 6 characters")
        return value


class UserUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    username: str | None = None
    password: str | None = None
    full_name: str | None = None
    is_active: bool | None = None

    @field_validator("username")
    @classmethod
    def normalize_optional_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("username cannot be empty")
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_optional_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value.strip()) < 6:
            raise ValueError("password must contain at least 6 characters")
        return value

    @field_validator("full_name")
    @classmethod
    def normalize_optional_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("full_name cannot be empty")
        return " ".join(value.strip().split())


class UserResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    username: str
    full_name: str
    is_active: bool
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AssignmentResponse(BaseModel):
    success: bool
    message: str
