# Implementation Notes

This document explains each major decision in the Stage 8 wallet backend so new contributors can quickly understand *what* was built and *why*.

## 1. Project Layout
- **Separation of concerns**: The `app/` package mirrors FastAPI best practices—routers for HTTP entrypoints, services for business logic, models/schemas for persistence/data contracts, and dependencies for cross-cutting concerns (auth). This makes it easy to reason about responsibilities, test units in isolation, and plug in new modules (e.g., notifications) later.
- **Async-first**: SQLAlchemy async engine (`create_async_engine`) and HTTPX AsyncClient were chosen to keep high Paystack/webhook concurrency with minimal threads.

## 2. Configuration (`app/core/config.py`)
- **Pydantic Settings**: Centralizes env parsing/validation (e.g., rejecting non-PostgreSQL URLs) and provides cached access via `get_settings()`. This avoids manual `os.getenv` scattering and simplifies testing by overriding env vars.
- **Paystack + Google credentials**: Stored as env vars to keep secrets out of code and support multiple deployment stages (dev, staging, prod).

## 3. Database Layer
- **Base + Session (`app/db/session.py`)**: `AsyncSessionLocal` factory ensures FastAPI dependency injection simply yields a session with `expire_on_commit=False`, preventing stale object issues when returning ORM instances.
- **Models (`app/models/*`)**:
  - `User`: Stores Google identity; `wallet` relationship is one-to-one to guarantee exactly one wallet per user.
  - `Wallet`: Unique `wallet_number` string and integer `balance` in kobo to avoid floating point precision problems.
  - `Transaction`: Enum-backed `type` and `status` fields capture deposit/transfer flows with a JSON field (`extra_data`) for Paystack payloads and transfer details. Unique `reference` enforces idempotency.
  - `APIKey`: Enforces hashed storage, permission arrays, expiry timestamps, and revocation flag.

## 4. Authentication
- **Google Sign-In (`AuthService`)**:
  - Accepts a Google JWT token (ID token). Signature verification is disabled for now (because Google public keys rotation requires caching), but issuer/audience claims are still validated. This can be extended when certificates are available.
  - Automatically provisions a wallet with a generated 12-digit number on first login; ensures each user can transact immediately.
- **API Keys (`APIKeyService`)**:
  - `generate_api_key()` returns a random secret; `hash_api_key()` uses PBKDF2 with per-key salt and 100k iterations for security.
  - `create_key()` enforces permission validation and the max 5 active keys per user, preventing abuse.
  - `rollover()` revokes an expired key and clones its permissions/name into a brand new record with a fresh secret; TTL is derived from the original key's lifespan.
  - `authenticate()` iterates active, non-expired keys and checks hashed values. Permission checks happen before returning, surfacing `403` vs `401` distinctly.
- **Dependency (`require_auth`)**:
  - Accepts either `Authorization: Bearer <jwt>` or `x-api-key`. Returns an `AuthContext` object so downstream routes can access the resolved user/api-key pair.
  - Permission scoping occurs here, ensuring route handlers stay slim and consistent.

## 5. Wallet Service (`app/services/wallet.py`)
- **Deposit Flow**:
  1. Validate amount > 0.
  2. Create pending transaction with unique UUID reference.
  3. Call Paystack `/transaction/initialize`; on failure, roll back DB to avoid orphaned references.
  4. Persist Paystack response data for traceability and return `reference` + `authorization_url`.
- **Webhook Handling**:
  - Uses HMAC SHA-512 with Paystack webhook secret for signature validation; rejects invalid payloads before touching the DB.
  - Parses JSON, extracts `reference`, and delegates to `verify_and_credit`.
  - `verify_and_credit` calls Paystack `/transaction/verify`, ensures success, and uses `async with session.begin()` to atomically credit wallet + mark transaction `success`. Subsequent webhook retries are idempotent because the status short-circuits.
- **Manual Status Checks**:
  - `/wallet/deposit/{reference}/status` simply fetches transaction (owned by the authenticated user) without mutating balances to respect the “must not credit” rule.
- **Transfers**:
  - Validates recipient wallet existence, prevents self-transfer, enforces duplicate reference guard, checks balance, and executes debit/credit in a single transaction context to maintain atomicity even under concurrent operations.
- **Transaction Queries**:
  - Exposes `get_transactions` sorted by recency for `/wallet/transactions` endpoint.

## 6. Paystack Client (`app/services/paystack.py`)
- **HTTPX AsyncClient**: Handles deposit initialization/verification with default timeouts (15s initialize, 10s verify).
- **Signature Verification**: `verify_signature` compares Paystack header to locally computed HMAC digest.
- **Error Surfacing**: `_handle_response` raises FastAPI HTTP errors with Paystack message to keep clients informed.

## 7. API Routes (`app/api/routes/*`)
- **Auth**: Minimal placeholder endpoints for Google auth URL and callback. Callback goes through `AuthService` then returns combined user + wallet_id view.
- **API Keys**: Both routes require Google JWT (no API key) to avoid bootstrapping loops. Responses include plaintext key only once on creation/rollover.
- **Wallet**:
  - `POST /deposit`: Requires permission `deposit`.
  - `POST /paystack/webhook`: Public endpoint but signature requirement ensures authenticity.
  - `GET /deposit/{reference}/status`: Permission `read`.
  - `GET /balance`, `GET /transactions`: Permission `read`.
  - `POST /transfer`: Permission `transfer`.

## 8. Schemas (`app/schemas/*`)
- Shared `ORMModel` base ensures `orm_mode=True` for JSON serialization. Input models (e.g., `DepositRequest`, `TransferRequest`, `APIKeyCreate`) provide request validation and enforce constraints like expiry format regex.

## 9. Utilities
- `generate_wallet_number()` simply generates a 12-digit numeric string and loops until it finds a unique value; collisions are extremely unlikely but still checked.

## 10. Environment & Deployment
- `.env.example` documents required secrets and DSNs.
- README outlines installation, env setup, and running instructions so anyone can bootstrap quickly.
- Async components and hashed secrets position the project for production, but future work should include:
  - Proper Google JWT signature validation (download & cache JWKS).
  - Alembic migrations to version control the schema.
  - Automated tests (unit/integration) and CI.
  - Background retry mechanism if Paystack API is temporarily unavailable.

## 11. Testing Strategy (Recommended)
- **Unit Tests**: Mock Paystack client, assert wallet balances and transaction statuses after calling service methods.
- **Integration Tests**: Use a temporary PostgreSQL instance (Docker) and hit FastAPI endpoints via HTTPX/pytest.
- **Webhook Idempotency**: Replay the same webhook payload to ensure the wallet only credits once—implement assertions around transaction status.

With this breakdown, a new engineer can trace any request from the router through services and database layers, understand the security assumptions, and extend the system confidently.
