import datetime

import pytest
from fastapi import HTTPException

from app.services.api_keys import APIKeyService
from tests.factories import create_user_with_wallet


@pytest.fixture(autouse=True)
def naive_datetime(monkeypatch):
    class NaiveDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return super().now()

        def replace(self, *args, **kwargs):
            return datetime.datetime.replace(self, *args, **kwargs)

    monkeypatch.setattr("app.services.api_keys.datetime", NaiveDateTime)


@pytest.mark.asyncio
async def test_api_key_creation_limit_enforced(db_session):
    user, _ = await create_user_with_wallet(
        db_session, email="key-owner@example.com", google_id="gid-key", balance=0
    )
    service = APIKeyService(db_session)
    secrets = []
    for idx in range(5):
        key, secret = await service.create_key(
            user,
            name=f"service-{idx}",
            permissions=["read"],
            expiry="1D",
        )
        assert secret
        secrets.append(secret)
        assert key.permissions == ["read"]

    with pytest.raises(HTTPException):
        await service.create_key(
            user,
            name="overflow",
            permissions=["read"],
            expiry="1D",
        )


@pytest.mark.asyncio
async def test_api_key_permission_required(db_session):
    user, _ = await create_user_with_wallet(
        db_session, email="perm@example.com", google_id="gid-perm", balance=0
    )
    service = APIKeyService(db_session)
    _, secret = await service.create_key(
        user,
        name="reader",
        permissions=["read"],
        expiry="1D",
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.authenticate(secret, required_permission="transfer")
    assert excinfo.value.status_code == 403
