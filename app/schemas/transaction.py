from datetime import datetime
from typing import Optional

from app.models.transaction import TransactionStatus, TransactionType
from app.schemas.base import ORMModel


class TransactionOut(ORMModel):
    id: int
    reference: str
    type: TransactionType
    amount: int
    status: TransactionStatus
    created_at: datetime
    extra_data: Optional[dict]
