from fastapi import APIRouter

from app.api.routes import auth, keys, wallet


def get_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(auth.router)
    router.include_router(keys.router)
    router.include_router(wallet.router)
    return router
