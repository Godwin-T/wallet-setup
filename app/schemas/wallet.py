from datetime import datetime
from typing import Optional

from app.schemas.base import ORMModel


class WalletOut(ORMModel):
    id: int
    wallet_number: str
    balance: int
    created_at: datetime


class DepositRequest(ORMModel):
    amount: int

    class Config:
        model_config = {
        "from_attributes": False
    }


class DepositResponse(ORMModel):
    reference: str
    authorization_url: str


class TransferRequest(ORMModel):
    recipient_wallet_number: str
    amount: int
    reference: Optional[str]


class TransferResponse(ORMModel):
    reference: str
    status: str
