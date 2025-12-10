import json
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, User, Wallet
from app.models.transaction import TransactionStatus, TransactionType
from app.services.paystack import PaystackClient


class WalletService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.paystack = PaystackClient()

    async def get_wallet_for_user(self, user: User) -> Wallet:
        result = await self.session.execute(select(Wallet).where(Wallet.user_id == user.id))
        wallet = result.scalar_one_or_none()
        if wallet:
            return wallet
        raise HTTPException(status_code=404, detail="Wallet not found")

    async def initialize_deposit(self, user: User, amount: int) -> dict:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")

        wallet = await self.get_wallet_for_user(user)
        reference = await self._ensure_unique_reference()

        transaction = Transaction(
            user_id=user.id,
            wallet_id=wallet.id,
            reference=reference,
            type=TransactionType.deposit,
            amount=amount,
            status=TransactionStatus.pending,
        )
        self.session.add(transaction)
        await self.session.flush()

        try:
            paystack_response = await self.paystack.initialize_transaction(
                email=user.email,
                amount=amount,
                reference=reference,
            )
        except Exception:
            await self.session.rollback()
            raise
        transaction.extra_data = paystack_response
        await self.session.commit()

        return {"reference": reference, "authorization_url": paystack_response["authorization_url"]}

    async def verify_and_credit(self, reference: str) -> Transaction:
        transaction = await self._get_transaction_by_reference(reference)
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")

        if transaction.status == TransactionStatus.success:
            return transaction

        verification = await self.paystack.verify_transaction(reference)
        if verification.get("status") != "success":
            transaction.status = TransactionStatus.failed
            await self.session.commit()
            raise HTTPException(status_code=400, detail="Paystack verification failed")

        wallet = await self.session.get(Wallet, transaction.wallet_id)
        async with self.session.begin():
            wallet.balance += transaction.amount
            transaction.status = TransactionStatus.success
            transaction.extra_data = verification

        await self.session.refresh(transaction)
        return transaction

    async def process_webhook(self, signature: str, raw_body: bytes) -> None:
        if not self.paystack.verify_signature(raw_body, signature):
            raise HTTPException(status_code=400, detail="Invalid Paystack signature")

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
        data = payload.get("data", {})
        reference = data.get("reference")
        if not reference:
            raise HTTPException(status_code=400, detail="Missing reference")
        await self.verify_and_credit(reference)

    async def transfer(
        self, sender_wallet: Wallet, recipient_wallet_number: str, amount: int, reference: Optional[str]
    ) -> Transaction:
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")

        recipient_wallet = await self._get_wallet_by_number(recipient_wallet_number)
        if not recipient_wallet:
            raise HTTPException(status_code=404, detail="Recipient wallet not found")

        if recipient_wallet.id == sender_wallet.id:
            raise HTTPException(status_code=400, detail="Cannot transfer to same wallet")

        reference = reference or await self._ensure_unique_reference()
        existing = await self._get_transaction_by_reference(reference)
        if existing:
            raise HTTPException(status_code=400, detail="Duplicate reference")

        if sender_wallet.balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")

        async with self.session.begin():
            sender_wallet.balance -= amount
            recipient_wallet.balance += amount
            transaction = Transaction(
                user_id=sender_wallet.user_id,
                wallet_id=sender_wallet.id,
                reference=reference,
                type=TransactionType.transfer,
                amount=amount,
                status=TransactionStatus.success,
                extra_data={
                    "recipient_wallet_id": recipient_wallet.id,
                    "recipient_wallet_number": recipient_wallet.wallet_number,
                },
            )
            self.session.add(transaction)

        await self.session.refresh(transaction)
        return transaction

    async def get_transactions(self, wallet: Wallet) -> list[Transaction]:
        result = await self.session.execute(
            select(Transaction).where(Transaction.wallet_id == wallet.id).order_by(Transaction.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_transaction_status(self, reference: str, user: User) -> Transaction:
        transaction = await self._get_transaction_by_reference(reference)
        if not transaction or transaction.user_id != user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return transaction

    async def _get_transaction_by_reference(self, reference: str) -> Optional[Transaction]:
        result = await self.session.execute(select(Transaction).where(Transaction.reference == reference))
        return result.scalar_one_or_none()

    async def _get_wallet_by_number(self, wallet_number: str) -> Optional[Wallet]:
        result = await self.session.execute(select(Wallet).where(Wallet.wallet_number == wallet_number))
        return result.scalar_one_or_none()

    async def _ensure_unique_reference(self) -> str:
        while True:
            reference = uuid.uuid4().hex
            existing = await self._get_transaction_by_reference(reference)
            if not existing:
                return reference
