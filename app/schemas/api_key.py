from datetime import datetime
from typing import List

from pydantic import BaseModel, Field
from app.schemas.base import ORMModel


class APIKeyCreate(BaseModel):
    name: str
    permissions: List[str]
    expiry: str = Field(pattern="^(1H|1D|1M|1Y)$")


class APIKeyOut(ORMModel):
    id: int
    name: str
    permissions: List[str]
    expires_at: datetime
    revoked: bool
    created_at: datetime


class APIKeyWithSecret(APIKeyOut):
    key: str


class APIKeyRollover(BaseModel):
    api_key_id: int


class APIKeyRevoke(BaseModel):
    api_key_id: int
