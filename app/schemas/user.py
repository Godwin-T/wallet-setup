from datetime import datetime

from app.schemas.base import ORMModel


class UserOut(ORMModel):
    id: int
    email: str
    google_id: str
    created_at: datetime
