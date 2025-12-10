from app.schemas.user import UserOut


class AuthResponse(UserOut):
    wallet_id: int
