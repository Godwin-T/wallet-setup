import asyncio
import logging
from contextlib import suppress

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api.routes import get_api_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.wallet import WalletService

settings = get_settings()
logger = logging.getLogger("wallet.background")

app = FastAPI(title=settings.app_name)
app.include_router(get_api_router())


@app.get("/health")
async def health_check():
    return {"status": "ok"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version="1.0.0",
        description="Wallet API documentation",
        routes=app.routes,
    )

    components = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    components["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    components["ApiKeyAuth"] = {
        "type": "apiKey",
        "name": "x-api-key",
        "in": "header",
    }

    for path in openapi_schema.get("paths", {}).values():
        for operation in path.values():
            operation.setdefault("security", [])
            operation["security"].append({"BearerAuth": []})
            operation["security"].append({"ApiKeyAuth": []})

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


async def paystack_verification_worker():
    interval = settings.paystack_verify_interval_seconds
    while True:
        try:
            async with AsyncSessionLocal() as session:
                service = WalletService(session)
                await service.retry_pending_transactions()
        except Exception as exc:  # pragma: no cover - background logging
            logger.exception("Verification worker error: %s", exc)
        await asyncio.sleep(interval if interval > 0 else 60)


@app.on_event("startup")
async def start_verification_worker():
    if settings.paystack_verify_worker_enabled:
        app.state.paystack_worker = asyncio.create_task(paystack_verification_worker())


@app.on_event("shutdown")
async def stop_verification_worker():
    task = getattr(app.state, "paystack_worker", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
