from app.models import User, Wallet
from app.utils.wallet import generate_wallet_number


async def create_user_with_wallet(session, *, email: str, google_id: str, balance: int = 0):
    user = User(email=email, google_id=google_id)
    session.add(user)
    await session.flush()
    wallet = Wallet(user_id=user.id, wallet_number=generate_wallet_number(), balance=balance)
    session.add(wallet)
    await session.commit()
    await session.refresh(user)
    await session.refresh(wallet)
    return user, wallet
