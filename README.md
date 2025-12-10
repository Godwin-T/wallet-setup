# Wallet Service Backend – FastAPI

Production-grade wallet infrastructure that satisfies the HNG Stage 8 requirements. The service exposes a FastAPI interface for Google Sign-In, wallet deposits via Paystack, webhook processing, wallet-to-wallet transfers, transaction history, and full API key lifecycle support.

## Features
- **Google Sign-In (JWT)**: Accepts Google ID tokens, auto-provisions users and wallets.
- **Wallet Management**: Auto-generated wallet numbers, integer balances (kobo), realtime transaction ledger.
- **Paystack Integration**: Deposit initialization, webhook signature verification, idempotent credits, background retry worker, and manual status checks.
- **Wallet-to-Wallet Transfers**: Atomic debits/credits enforced through database transactions.
- **API Keys**: Hashed storage, permissions (read/deposit/transfer), expiry presets, max 5 active keys/user, rollover of expired keys.
- **Auth Middleware**: Supports both `Authorization: Bearer <jwt>` and `x-api-key` flows with permission enforcement.
- **PostgreSQL + SQLAlchemy**: Async engine with repository/service layering for clean separation.
- **Robust Error Responses**: Global FastAPI exception handler plus contextual HTTP errors around Paystack/DB ops keep clients from seeing raw stack traces.

## Project Structure
```
app/
  api/routes/         # FastAPI routers (auth, keys, wallet)
  core/               # Settings and security helpers
  db/                 # SQLAlchemy base + session
  dependencies/       # Shared dependency functions (auth contexts)
  models/             # SQLAlchemy ORM models
  schemas/            # Pydantic request/response models
  services/           # Business logic (auth, wallet, Paystack, API keys)
  utils/              # Utility helpers (wallet number generation)
tests/                # Placeholder for future automated tests
.env.example          # Reference environment variables
README.md             # This document
IMPLEMENTATION_NOTES.md # Deep dive into decisions/explanations
```

## Getting Started

### 1. Clone & Install
```bash
git clone <repo> wallet-service && cd wallet-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # create this file listing FastAPI, SQLAlchemy, asyncpg, httpx, PyJWT, python-dotenv, etc.
```

### 2. Configure Environment
Create `.env` from `.env.example` and adjust values:
```
DATABASE_URL=postgresql+asyncpg://wallet:wallet@localhost:5432/wallet_service
PAYSTACK_SECRET_KEY=psk_test_xxx
PAYSTACK_BASE_URL=https://api.paystack.co
PAYSTACK_WEBHOOK_SECRET=whsec_xxx
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
JWT_ISSUER=accounts.google.com
API_KEY_LIMIT=5
PAYSTACK_VERIFY_INTERVAL_SECONDS=60
PAYSTACK_VERIFY_BACKOFF_SECONDS=120
PAYSTACK_VERIFY_THRESHOLD_ATTEMPTS=5
PAYSTACK_VERIFY_WORKER_ENABLED=true
```

### 3. Database
1. Create the PostgreSQL database described in `DATABASE_URL`.
2. Apply migrations via Alembic:
   ```bash
   alembic upgrade head
   ```
   (Use `alembic revision --autogenerate -m "message"` to create future migrations.)

### 4. Run Application
```bash
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs` for the automatically generated Swagger UI.

## Core Components
- **Settings (`app/core/config.py`)**: Central place for env vars, includes validation for PostgreSQL URLs.
- **DB Session (`app/db/session.py`)**: Async engine and session dependency.
- **Models (`app/models/*`)**: Users, Wallets, Transactions (with enums/status), API Keys (hashed storage, permissions, expiry).
- **Services (`app/services/*`)**:
  - `AuthService`: Google token decoding, user & wallet provisioning.
  - `APIKeyService`: Creation, verification, rolling expired keys, permission enforcement.
  - `WalletService`: Deposit init, Paystack verification, webhook handling, transfers, transaction listing.
  - `PaystackClient`: HTTPX wrapper for initialization/verification plus webhook signature validation.
- **Dependencies (`app/dependencies/auth.py`)**: Handles both JWT and API key authentication, returns `AuthContext` used by routes to determine permissions.

## API Overview
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/auth/google` | GET | None | Returns Google OAuth metadata (client ID). |
| `/auth/google/callback` | GET | Query `token` | Validates Google token, creates user + wallet, returns profile. |
| `/keys/create` | POST | Bearer JWT | Creates API key (permissions + expiry) and returns hashed record with plaintext key once. |
| `/keys/rollover` | POST | Bearer JWT | Generates a new key for an expired one while revoking the old. |
| `/wallet/deposit` | POST | Bearer JWT or API key (`deposit`) | Initializes Paystack transaction and records pending transaction. |
| `/wallet/paystack/webhook` | POST | Paystack signature | Idempotent webhook to verify and credit completed deposits. |
| `/wallet/deposit/{reference}/status` | GET | Bearer/API key (`read`) | Reads status; with `refresh=true` (default) it hits Paystack verify API and updates the DB as a fallback. |
| `/wallet/balance` | GET | Bearer/API key (`read`) | Returns wallet balance and basic wallet details. |
| `/wallet/transfer` | POST | Bearer/API key (`transfer`) | Atomic wallet-to-wallet transfer with duplicate reference guard. |
| `/wallet/transactions` | GET | Bearer/API key (`read`) | Returns wallet transactions sorted by newest first. |

Refer to the OpenAPI schema (`/docs`) for request/response bodies.

## Paystack Notes
- Deposits use `/transaction/initialize`; the Paystack response is stored alongside the transaction (`extra_data`).
- Webhook validation uses `x-paystack-signature` header (HMAC SHA-512).
- A background worker re-verifies pending deposits via `/transaction/verify/{reference}` every minute and backs off to every two minutes once an entry reaches five attempts, ensuring credit even if a webhook is missed.
- Manual status lookup (`refresh=true`) also triggers a verification attempt and persists any new state.

## API Key Rules
- Max 5 active (non-expired, non-revoked) keys per user.
- Hashes stored using PBKDF2 and never returned.
- Permissions: `read`, `deposit`, `transfer`.
- Expiry presets: `1H`, `1D`, `1M`, `1Y`.
- Rollover allowed only once a key is expired; new key inherits permissions/name and revokes the old record.

## Testing Guidance
- **Unit Tests**: Mock out Paystack (HTTPX) to simulate initialize/verify flows; exercise API key creation/rollover and permission enforcement.
- **Integration Tests**: Spin up a temporary PostgreSQL DB (e.g., via Docker) and run against Uvicorn + HTTP calls.
- **Webhook Tests**: Provide signed payloads validating idempotency (repeat webhook for same reference credits only once).

## Error Handling
- Input validation is enforced via Pydantic schemas (permissions, expiry options, Paystack reference path params, etc.).
- Domain errors raise `HTTPException` with explicit messages (insufficient balance, invalid API key, duplicate references, expired keys).
- External calls (Paystack, Google OAuth) are wrapped so network issues surface as `502` JSON responses rather than stack traces.
- A global exception handler logs unexpected failures server-side and returns `{ "detail": "Internal server error" }` so clients never see HTML debug pages.
- Duplicate users/API keys and transfer transaction faults roll back their DB sessions and emit concise `400/409/500` responses instead of raw SQLAlchemy errors.

## Deployment Notes
- Deploy via Uvicorn/Gunicorn with workers sized for async workloads.
- Store Paystack secrets and Google client IDs as environment variables (never commit).
- Terminate SSL at a reverse proxy and enforce HTTPS for JWT/API key confidentiality.
- Add observability (request logging, metrics) and queueing if webhook throughput grows.
- If background verification is undesirable in some environments, disable it with `PAYSTACK_VERIFY_WORKER_ENABLED=false`.

## License
MIT or as defined by the repository owner.
