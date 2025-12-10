import pytest
from sqlalchemy import select

from app.models import Wallet
from app.services.auth import AuthService


@pytest.mark.asyncio
async def test_google_login_creates_user_and_wallet(db_session, monkeypatch):
    payload = {"sub": "gid-123", "email": "new-user@example.com"}
    monkeypatch.setattr(AuthService, "decode_google_token", lambda self, token: payload)

    service = AuthService(db_session)
    user = await service.get_or_create_user("token")
    assert user.id is not None

    wallet_result = await db_session.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = wallet_result.scalar_one()
    assert wallet.balance == 0

    # second login returns same user
    same_user = await service.get_or_create_user("token")
    assert same_user.id == user.id
