# NEXUS - Production Reliability & Recovery Platform

NEXUS is an intelligent production reliability and automated recovery platform. Its long-term vision is to monitor production services, correlate metrics, logs, traces, and deployments, detect incidents with precision, identify root causes, and execute safe, controlled recovery actions.

---

## Current Project Status

- **Phase 0: Backend Foundation** (Completed)
  - Modular monolith architecture (`app/core`, `app/db`, `app/api`)
  - Structured application logging (JSON / formatted text)
  - Environment-driven configuration via Pydantic Settings
  - SQLAlchemy 2.0 Async ORM with connection pooling
  - Health check endpoints (`/health` and `/health/db`)
  - Docker & Docker Compose setup (FastAPI + PostgreSQL)

- **Phase 1: Authentication & Identity Foundation** (Completed & Verified)
  - User registration with OWASP-recommended **Argon2id** password hashing
  - Database entities: `User`, `Session`, `EmailVerificationToken`
  - Short-lived JWT access tokens (15-minute default)
  - Cryptographically secure 256-bit refresh tokens with **SHA-256 database hashing**
  - **Single-use refresh token rotation** with **Token Family Reuse Detection**
  - Session revocation on logout and automatic lockout on reuse attack
  - Local email verification abstraction (safe console logger for dev mode)
  - Alembic migrations for all Phase 1 schema tables
  - Real PostgreSQL integration test suite (**29 tests, 100% passing**)

---

## Local Prerequisites

- **Python**: 3.11+ (or [uv](https://github.com/astral-sh/uv))
- **PostgreSQL**: 16+ (via Docker Compose or local server)

---

## Environment Variables Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `POSTGRES_USER` | `nexus` | Database superuser/app user |
| `POSTGRES_PASSWORD` | `nexus_secret` | Database password |
| `POSTGRES_DB` | `nexus_db` | Primary application database |
| `JWT_SECRET_KEY` | *(change in production)* | Secret key for signing access tokens |
| `JWT_ALGORITHM` | `HS256` | JWT signature algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Short-lived access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token session TTL |
| `EMAIL_VERIFICATION_EXPIRE_HOURS`| `24` | Email verification token validity window |
| `EMAIL_SERVICE_PROVIDER` | `console` | `console` for local dev, `mock` for testing |

---

## How to Start the Project

### Option A: Using Docker Compose (Recommended)

```bash
# Build and run containers
docker compose up --build
```

Endpoints:
- Application Liveness: [http://localhost:8000/health](http://localhost:8000/health)
- Database Readiness: [http://localhost:8000/health/db](http://localhost:8000/health/db)
- Interactive OpenAPI Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option B: Local Python Development

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Database Migrations

From `backend/`:

```bash
# Generate a new migration after model changes
alembic revision --autogenerate -m "describe_changes"

# Apply pending migrations
alembic upgrade head

# Roll back the previous migration
alembic downgrade -1
```

---

## How to Run Tests

Tests run against an isolated live PostgreSQL test database (`nexus_test_db`):

```bash
cd backend
pytest -v
```

---

## Authentication API Reference

Detailed architecture documentation is available in [docs/architecture/auth.md](docs/architecture/auth.md).

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | Register new user account with Argon2id hash |
| `POST` | `/api/v1/auth/login` | Login and obtain access + refresh tokens |
| `POST` | `/api/v1/auth/refresh` | Rotate refresh token with reuse detection |
| `POST` | `/api/v1/auth/logout` | Revoke session |
| `GET` | `/api/v1/auth/me` | Retrieve authenticated user profile (Bearer token) |
| `POST` | `/api/v1/auth/verify-email` | Verify user email address |
