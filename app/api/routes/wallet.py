from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.dependencies.auth import AuthContext, require_auth
from app.schemas.transaction import TransactionOut
from app.schemas.wallet import DepositRequest, DepositResponse, TransferRequest, TransferResponse, WalletOut
from app.services.wallet import WalletService

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.post("/deposit", response_model=DepositResponse)
async def initialize_deposit(
    payload: DepositRequest,
    context: AuthContext = Depends(require_auth("deposit")),
    session: AsyncSession = Depends(get_session),
):
    wallet_service = WalletService(session)
    result = await wallet_service.initialize_deposit(context.user, payload.amount)
    return DepositResponse(**result)


@router.post("/paystack/webhook")
async def paystack_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    wallet_service = WalletService(session)
    signature = request.headers.get("x-paystack-signature")
    body = await request.body()
    await wallet_service.process_webhook(signature or "", body)
    return {"status": "processed"}


@router.get("/deposit/{reference}/status", response_model=TransactionOut)
async def deposit_status(
    reference: str,
    context: AuthContext = Depends(require_auth("read")),
    session: AsyncSession = Depends(get_session),
):
    wallet_service = WalletService(session)
    transaction = await wallet_service.get_transaction_status(reference, context.user)
    return transaction


@router.get("/balance", response_model=WalletOut)
async def wallet_balance(
    context: AuthContext = Depends(require_auth("read")),
    session: AsyncSession = Depends(get_session),
):
    wallet_service = WalletService(session)
    wallet = await wallet_service.get_wallet_for_user(context.user)
    return wallet


@router.post("/transfer", response_model=TransferResponse)
async def wallet_transfer(
    payload: TransferRequest,
    context: AuthContext = Depends(require_auth("transfer")),
    session: AsyncSession = Depends(get_session),
):
    wallet_service = WalletService(session)
    wallet = await wallet_service.get_wallet_for_user(context.user)
    transaction = await wallet_service.transfer(wallet, payload.recipient_wallet_number, payload.amount, payload.reference)
    return TransferResponse(reference=transaction.reference, status=transaction.status.value)


@router.get("/transactions", response_model=list[TransactionOut])
async def wallet_transactions(
    context: AuthContext = Depends(require_auth("read")),
    session: AsyncSession = Depends(get_session),
):
    wallet_service = WalletService(session)
    wallet = await wallet_service.get_wallet_for_user(context.user)
    transactions = await wallet_service.get_transactions(wallet)
    return transactions
