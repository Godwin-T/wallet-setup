from datetime import datetime, timedelta, timezone
from typing import Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import generate_api_key, hash_api_key, verify_api_key
from app.models import APIKey, User


class APIKeyService:
    VALID_PERMISSIONS = {"read", "deposit", "transfer"}

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def create_key(self, user: User, *, name: str, permissions: list[str], expiry: str) -> Tuple[APIKey, str]:
        await self._enforce_limit(user.id)
        invalid = set(permissions) - self.VALID_PERMISSIONS
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid permissions: {', '.join(invalid)}")
        expires_at = self._expiry_to_datetime(expiry)

        raw_key = generate_api_key()
        hashed, _ = hash_api_key(raw_key)
        api_key = APIKey(
            user_id=user.id,
            name=name,
            permissions=permissions,
            key_hash=hashed,
            expires_at=expires_at,
        )
        self.session.add(api_key)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail="Could not create API key") from exc
        await self.session.refresh(api_key)
        return api_key, raw_key

    async def rollover(self, user: User, api_key_id: int) -> Tuple[APIKey, str]:
        source_key = await self.session.get(APIKey, api_key_id)
        if not source_key or source_key.user_id != user.id:
            raise HTTPException(status_code=404, detail="API key not found")
        if source_key.revoked:
            raise HTTPException(status_code=400, detail="API key revoked")
        if source_key.expires_at > datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="API key not expired")

        raw_key = generate_api_key()
        hashed, _ = hash_api_key(raw_key)
        ttl = source_key.expires_at - source_key.created_at
        if ttl <= timedelta():
            ttl = timedelta(days=30)
        new_key = APIKey(
            user_id=user.id,
            name=source_key.name,
            permissions=source_key.permissions,
            key_hash=hashed,
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        source_key.revoked = True
        self.session.add(new_key)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail="Could not rollover API key") from exc
        await self.session.refresh(new_key)
        return new_key, raw_key

    async def authenticate(self, raw_key: str, required_permission: str | None = None) -> APIKey:
        stmt = (
            select(APIKey)
            .options(selectinload(APIKey.user))
            .where(APIKey.revoked.is_(False))
        )
        result = await self.session.execute(stmt)
        now = datetime.now(timezone.utc)
        for api_key in result.scalars().all():
            if api_key.expires_at <= now:
                continue
            if verify_api_key(raw_key, api_key.key_hash):
                if required_permission and required_permission not in (api_key.permissions or []):
                    raise HTTPException(status_code=403, detail="Permission denied")
                return api_key
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired API key")

    async def _enforce_limit(self, user_id: int) -> None:
        stmt = select(APIKey).where(APIKey.user_id == user_id, APIKey.revoked.is_(False))
        result = await self.session.execute(stmt)
        active = [key for key in result.scalars().all() if key.expires_at > datetime.now(timezone.utc)]
        if len(active) >= self.settings.api_key_limit:
            raise HTTPException(status_code=400, detail="Maximum active API keys reached")

    def _expiry_to_datetime(self, expiry: str) -> datetime:
        delta_map = {
            "1H": timedelta(hours=1),
            "1D": timedelta(days=1),
            "1M": timedelta(days=30),
            "1Y": timedelta(days=365),
        }
        if expiry not in delta_map:
            raise HTTPException(status_code=400, detail="Invalid expiry option")
        return datetime.now(timezone.utc) + delta_map[expiry]
