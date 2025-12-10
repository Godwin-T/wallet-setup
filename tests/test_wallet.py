import json

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import Transaction, User, Wallet
from app.models.transaction import TransactionStatus
from app.services.paystack import PaystackClient
from app.services.wallet import WalletService
from tests.factories import create_user_with_wallet


async def fake_initialize_transaction(self, *, email: str, amount: int, reference: str):
    return {
        "authorization_url": f"https://paystack.test/pay/{reference}",
        "reference": reference,
        "amount": amount,
        "email": email,
    }


async def fake_verify_transaction(self, reference: str):
    return {"status": "success", "reference": reference}


def always_valid_signature(self, body: bytes, signature: str | None) -> bool:
    return True


@pytest.mark.asyncio
async def test_initialize_deposit_records_pending_transaction(db_session, monkeypatch):
    monkeypatch.setattr(PaystackClient, "initialize_transaction", fake_initialize_transaction, raising=False)
    user, _ = await create_user_with_wallet(
        db_session, email="wallet@test.com", google_id="gid-wallet", balance=0
    )
    service = WalletService(db_session)

    result = await service.initialize_deposit(user, 1500)
    assert "reference" in result and "authorization_url" in result

    stmt = select(Transaction).where(Transaction.reference == result["reference"])
    transaction = (await db_session.execute(stmt)).scalar_one()
    assert transaction.status == TransactionStatus.pending


@pytest.mark.asyncio
async def test_transfer_moves_funds_atomically(db_session):
    sender, sender_wallet = await create_user_with_wallet(
        db_session, email="sender@example.com", google_id="gid-sender", balance=10_000
    )
    recipient, recipient_wallet = await create_user_with_wallet(
        db_session, email="recipient@example.com", google_id="gid-recipient", balance=0
    )
    await db_session.commit()

    async with AsyncSessionLocal() as session:
        service = WalletService(session)
        sender_wallet = await session.get(Wallet, sender_wallet.id)
        recipient_wallet = await session.get(Wallet, recipient_wallet.id)
        await session.commit()

        transaction = await service.transfer(sender_wallet, recipient_wallet.wallet_number, 2500, reference=None)
        assert transaction.status == TransactionStatus.success

        updated_sender = await session.get(Wallet, sender_wallet.id)
        updated_recipient = await session.get(Wallet, recipient_wallet.id)
        assert updated_sender.balance == 7500
        assert updated_recipient.balance == 2500


@pytest.mark.asyncio
async def test_webhook_processing_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(PaystackClient, "initialize_transaction", fake_initialize_transaction, raising=False)
    monkeypatch.setattr(PaystackClient, "verify_transaction", fake_verify_transaction, raising=False)
    monkeypatch.setattr(PaystackClient, "verify_signature", always_valid_signature, raising=False)
    user, _ = await create_user_with_wallet(
        db_session, email="webhook@example.com", google_id="gid-webhook", balance=0
    )
    await db_session.commit()

    async with AsyncSessionLocal() as session:
        service = WalletService(session)
        user_obj = await session.get(User, user.id)
        await session.commit()

        deposit = await service.initialize_deposit(user_obj, 3000)
        reference = deposit["reference"]
        payload = json.dumps({"event": "charge.success", "data": {"reference": reference}}).encode()

        await service.process_webhook(signature="sig", raw_body=payload)
        wallet = await service.get_wallet_for_user(user_obj)
        assert wallet.balance == 3000

        await service.process_webhook(signature="sig", raw_body=payload)
        wallet_again = await service.get_wallet_for_user(user_obj)
        assert wallet_again.balance == 3000


@pytest.mark.asyncio
async def test_retry_pending_transactions_marks_success(db_session, monkeypatch):
    monkeypatch.setattr(PaystackClient, "initialize_transaction", fake_initialize_transaction, raising=False)
    monkeypatch.setattr(PaystackClient, "verify_transaction", fake_verify_transaction, raising=False)
    user, _ = await create_user_with_wallet(
        db_session, email="retry@example.com", google_id="gid-retry", balance=0
    )
    service = WalletService(db_session)
    deposit = await service.initialize_deposit(user, 2000)

    processed = await service.retry_pending_transactions()
    assert processed == 1

    transaction = await service.get_transaction_status(deposit["reference"], user)
    assert transaction.status == TransactionStatus.success


@pytest.mark.asyncio
async def test_status_refresh_triggers_paystack_check(db_session, monkeypatch):
    monkeypatch.setattr(PaystackClient, "initialize_transaction", fake_initialize_transaction, raising=False)
    monkeypatch.setattr(PaystackClient, "verify_transaction", fake_verify_transaction, raising=False)
    user, _ = await create_user_with_wallet(
        db_session, email="manual@example.com", google_id="gid-manual", balance=0
    )
    service = WalletService(db_session)
    deposit = await service.initialize_deposit(user, 1500)

    transaction = await service.get_transaction_status(deposit["reference"], user, refresh=True)
    assert transaction.status == TransactionStatus.success
