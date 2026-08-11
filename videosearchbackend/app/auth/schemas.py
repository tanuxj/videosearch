"""Request and response models for the auth routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120, examples=["Alex Rivera"])
    email: EmailStr = Field(examples=["alex@company.com"])
    # 8 is the floor the UI enforces; the 128 ceiling just bounds hashing work.
    password: str = Field(min_length=8, max_length=128, examples=["correct-horse-battery"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """Public view of an account — never includes the password digest."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    """Access token payload.

    The refresh token is intentionally absent: it travels only in an
    httpOnly cookie, so client-side JavaScript can never read it.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    user: UserOut


class MessageResponse(BaseModel):
    detail: str
