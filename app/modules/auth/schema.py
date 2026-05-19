from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.users.schema import UserResponse


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("The field cannot be empty")
        return value.strip()


class TokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
