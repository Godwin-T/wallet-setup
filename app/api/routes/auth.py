from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.auth import AuthResponse
from app.services.auth import AuthService
from app.services.wallet import WalletService
from urllib.parse import urlencode
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/google")
async def initiate_google_login_redirect():

    settings = get_settings()
    base = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": str(settings.google_redirect_uri),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{base}?{urlencode(params)}"
    return {"url": auth_url}


@router.get("/google/callback",) # response_model=AuthResponse
async def google_callback(code: str, session: AsyncSession = Depends(get_session)):
    auth_service = AuthService(session)
    id_token = await auth_service.exchange_code_for_token(code)
    user = await auth_service.get_or_create_user(id_token)
    wallet_service = WalletService(session)
    wallet = await wallet_service.get_wallet_for_user(user)
    return {"user": AuthResponse(
        id=user.id,
        email=user.email,
        google_id=user.google_id,
        created_at=user.created_at,
        wallet_id=wallet.id,
    ), "id_token": id_token}
