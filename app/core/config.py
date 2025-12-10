from functools import lru_cache
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Wallet Service"
    database_url: str
    paystack_secret_key: str
    paystack_base_url: AnyHttpUrl = "https://api.paystack.co"
    paystack_webhook_secret: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: AnyHttpUrl
    jwt_issuer: str = "accounts.google.com"
    api_key_limit: int = 10
    default_currency: str = "NGN"

    class Config:
        case_sensitive = False
        env_file = ".env"

    @field_validator("database_url")
    def validate_db_url(cls, v: str) -> str:
        if v.startswith("postgresql"):
            return v
        if v.startswith("sqlite+aiosqlite"):
            return v
        raise ValueError("Database URL must use PostgreSQL (prod) or sqlite+aiosqlite (testing).")


@lru_cache
def get_settings() -> Settings:
    return Settings()
