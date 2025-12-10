import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.models import Transaction, User, Wallet
from app.models.transaction import TransactionStatus, TransactionType
from app.services.paystack import PaystackClient


class WalletService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.paystack = PaystackClient()
        self.settings = get_settings()

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

        await self._attempt_verification(transaction, force=True)
        if transaction.status != TransactionStatus.success:
            raise HTTPException(status_code=400, detail="Paystack verification failed")
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

        ctx_manager = self.session.begin_nested() if self.session.in_transaction() else self.session.begin()
        try:
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
            await self.session.flush()  # Flush to get the ID assigned
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise HTTPException(status_code=500, detail="Transfer failed") from exc
        return transaction

    async def get_transactions(self, wallet: Wallet) -> list[Transaction]:
        result = await self.session.execute(
            select(Transaction).where(Transaction.wallet_id == wallet.id).order_by(Transaction.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_transaction_status(self, reference: str, user: User, refresh: bool = False) -> Transaction:
        transaction = await self._get_transaction_by_reference(reference)
        if not transaction or transaction.user_id != user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")
        if refresh and transaction.status == TransactionStatus.pending:
            await self._attempt_verification(transaction, force=True)
            await self.session.refresh(transaction)
        return transaction

    async def retry_pending_transactions(self) -> int:
        stmt = select(Transaction).where(Transaction.status == TransactionStatus.pending)
        result = await self.session.execute(stmt)
        transactions = result.scalars().all()
        processed = 0
        for transaction in transactions:
            try:
                updated = await self._attempt_verification(transaction, force=False)
            except Exception:
                await self.session.rollback()
                continue
            if updated:
                processed += 1
        return processed

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

    async def _attempt_verification(self, transaction: Transaction, *, force: bool) -> bool:
        if transaction.status != TransactionStatus.pending:
            return False
        if not force and not self._is_attempt_due(transaction):
            return False

        self._update_verification_metadata(transaction)
        try:
            verification = await self.paystack.verify_transaction(transaction.reference)
        except HTTPException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            raise HTTPException(status_code=502, detail="Unable to verify transaction") from exc

        status = verification.get("status")
        if status == "success":
            await self._apply_success(transaction, verification)
        elif status == "failed":
            transaction.status = TransactionStatus.failed
            transaction.extra_data = verification
        else:
            transaction.extra_data = verification

        await self.session.commit()
        return True

    def _is_attempt_due(self, transaction: Transaction) -> bool:
        last_attempt = transaction.last_verification_attempt
        if not last_attempt:
            return True
        wait_seconds = self._required_wait_seconds(transaction.verification_attempts)
        return self._now() - last_attempt >= timedelta(seconds=wait_seconds)

    def _required_wait_seconds(self, attempts: int) -> int:
        if attempts >= self.settings.paystack_verify_threshold_attempts:
            return self.settings.paystack_verify_backoff_seconds
        return self.settings.paystack_verify_interval_seconds

    def _update_verification_metadata(self, transaction: Transaction) -> None:
        transaction.verification_attempts += 1
        transaction.last_verification_attempt = self._now()

    async def _apply_success(self, transaction: Transaction, verification: dict) -> None:
        wallet = await self.session.get(Wallet, transaction.wallet_id)
        wallet.balance += transaction.amount
        transaction.status = TransactionStatus.success
        transaction.extra_data = verification

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
