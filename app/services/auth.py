from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User, Wallet
from app.utils.wallet import generate_wallet_number


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def exchange_code_for_token(self, code: str) -> str:
        payload = {
            "code": code,
            "client_id": self.settings.google_client_id,
            "client_secret": self.settings.google_client_secret,
            "redirect_uri": str(self.settings.google_redirect_uri),
            "grant_type": "authorization_code",
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data=payload,
                    timeout=10,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Unable to reach Google OAuth") from exc

        if response.status_code >= 400:
            detail = response.json().get("error_description") if response.headers.get("content-type", "").startswith(
                "application/json"
            ) else response.text
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail or "Google exchange failed")

        data = response.json()
        id_token = data.get("id_token")
        if not id_token:
            raise HTTPException(status_code=400, detail="Google response missing id_token")
        return id_token

    def decode_google_token(self, token: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                options={"verify_signature": False},
                audience=self.settings.google_client_id,
                issuer=self.settings.jwt_issuer,
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token") from exc
        return payload

    async def get_or_create_user(self, token: str) -> User:
        payload = self.decode_google_token(token)
        google_id = payload.get("sub")
        email = payload.get("email")
        if not google_id or not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incomplete Google profile")

        user = await self._get_user_by_google_id(google_id)
        if user:
            return user

        user = User(email=email, google_id=google_id)
        self.session.add(user)
        await self.session.flush()
        wallet_number = await self._generate_unique_wallet_number()
        wallet = Wallet(user_id=user.id, wallet_number=wallet_number, balance=0)
        self.session.add(wallet)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def _generate_unique_wallet_number(self) -> str:
        while True:
            number = generate_wallet_number()
            result = await self.session.execute(select(Wallet).where(Wallet.wallet_number == number))
            if not result.scalar_one_or_none():
                return number

    async def _get_user_by_google_id(self, google_id: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.google_id == google_id))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
