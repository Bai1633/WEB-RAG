"""Pydantic schemas for authentication."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    """Login request body."""

    email: EmailStr
    # 登录不强制密码强度规则（历史弱密码用户仍可登录）；仅要求非空非超长。
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    """Register request body."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """Enforce a minimum password strength on registration."""
        if not any(ch.islower() for ch in value):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(ch.isupper() for ch in value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(ch.isdigit() for ch in value):
            raise ValueError("Password must contain at least one digit")
        return value


class TokenResponse(BaseModel):
    """Token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshTokenRequest(BaseModel):
    """Refresh token request body."""

    refresh_token: str


class UserResponse(BaseModel):
    """User response model."""

    id: UUID
    email: str
    is_active: bool
    is_superuser: bool

    model_config = {"from_attributes": True}
