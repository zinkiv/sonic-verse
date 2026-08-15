"""Auth request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: Literal["admin", "user"] = "user"


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class AdminSetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1)


class PatchUserRequest(BaseModel):
    disabled: bool | None = None


class UserPublic(BaseModel):
    id: str
    username: str
    role: str
    disabled: bool
    created_at: datetime


class LoginResult(BaseModel):
    token: str
    user: UserPublic


class AuthStatus(BaseModel):
    setup_required: bool
    user: UserPublic | None = None


class UserListResponse(BaseModel):
    users: list[UserPublic]
