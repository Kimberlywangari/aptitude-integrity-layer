from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["reviewer", "admin"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    email: str
    role: Role


class MeResponse(BaseModel):
    email: str
    role: Role
