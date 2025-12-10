from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.routes import get_api_router
from app.core.config import get_settings

settings = get_settings()

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
