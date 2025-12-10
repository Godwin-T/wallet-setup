from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.dependencies.auth import get_authenticated_user
from app.models import User
from app.schemas.api_key import APIKeyCreate, APIKeyRollover, APIKeyWithSecret
from app.services.api_keys import APIKeyService

router = APIRouter(prefix="/keys", tags=["api_keys"])


@router.post("/create", response_model=APIKeyWithSecret)
async def create_api_key(
    payload: APIKeyCreate,
    current_user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    service = APIKeyService(session)
    api_key, raw_key = await service.create_key(
        current_user,
        name=payload.name,
        permissions=payload.permissions,
        expiry=payload.expiry,
    )
    return APIKeyWithSecret(
        id=api_key.id,
        name=api_key.name,
        permissions=api_key.permissions,
        expires_at=api_key.expires_at,
        revoked=api_key.revoked,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.post("/rollover", response_model=APIKeyWithSecret)
async def rollover_api_key(
    payload: APIKeyRollover,
    current_user: User = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    service = APIKeyService(session)
    api_key, raw_key = await service.rollover(current_user, payload.api_key_id)
    return APIKeyWithSecret(
        id=api_key.id,
        name=api_key.name,
        permissions=api_key.permissions,
        expires_at=api_key.expires_at,
        revoked=api_key.revoked,
        created_at=api_key.created_at,
        key=raw_key,
    )
