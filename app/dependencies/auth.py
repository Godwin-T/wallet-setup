from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import APIKey, User
from app.services.api_keys import APIKeyService
from app.services.auth import AuthService


@dataclass
class AuthContext:
    user: Optional[User] = None
    api_key: Optional[APIKey] = None


async def get_authenticated_user(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = _extract_bearer_token(authorization)
    auth_service = AuthService(session)
    return await auth_service.get_or_create_user(token)


def require_auth(permission: str | None = None) -> Callable:
    async def dependency(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None, alias="x-api-key"),
        session: AsyncSession = Depends(get_session),
    ) -> AuthContext:
        if authorization:
            token = _extract_bearer_token(authorization)
            auth_service = AuthService(session)
            user = await auth_service.get_or_create_user(token)
            return AuthContext(user=user)

        if x_api_key:
            service = APIKeyService(session)
            api_key = await service.authenticate(x_api_key, permission)
            user = await session.get(User, api_key.user_id)
            return AuthContext(user=user, api_key=api_key)

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    return dependency


def _extract_bearer_token(header: str) -> str:
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    return token.strip()
