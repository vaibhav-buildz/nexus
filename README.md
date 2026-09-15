# NEXUS - Production Reliability & Recovery Platform

NEXUS is an intelligent production reliability and automated recovery platform. Its long-term vision is to monitor production services, correlate metrics, logs, traces, and deployments, detect incidents with precision, identify root causes, and execute safe, controlled recovery actions.

## Current Project Status

**Milestone: Backend Foundation (Modular Monolith)**
- Core FastAPI application with modern lifespan management (startup & shutdown)
- Structured application logging (JSON / formatted text)
- Environment-driven configuration via Pydantic Settings
- SQLAlchemy 2.0 Async ORM with connection pooling
- Alembic database migration scaffolding
- Health check endpoints (`/health` and `/health/db`)
- Global production error handling
- Docker & Docker Compose setup (FastAPI + PostgreSQL)
- Automated Pytest test suite with AsyncClient and in-memory SQLite isolation

---

## Local Prerequisites

- **Python**: 3.11+ (or [uv](https://github.com/astral-sh/uv) package manager)
- **Docker & Docker Compose**: For containerized execution and local PostgreSQL database

---

## How to Start the Project

### Option A: Using Docker Compose (Recommended)

1. **Copy the environment configuration**:
   ```bash
   cp .env.example .env
   ```

2. **Start PostgreSQL and the Backend**:
   ```bash
   docker compose up --build
   ```

3. **Verify the services**:
   - Application Health: [http://localhost:8000/health](http://localhost:8000/health)
   - Database Health: [http://localhost:8000/health/db](http://localhost:8000/health/db)
   - Interactive OpenAPI Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option B: Local Development (Direct Python)

1. **Navigate to the backend directory and create a virtual environment**:
   ```bash
   cd backend
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/macOS
   source .venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start PostgreSQL**:
   Make sure PostgreSQL is running locally or start only the DB container via Docker Compose:
   ```bash
   docker compose up -d postgres
   ```

4. **Run the FastAPI server**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## How to Run Migrations

Database migrations are managed using Alembic. Run commands from the `backend/` directory:

1. **Generate a new migration after schema changes**:
   ```bash
   alembic revision --autogenerate -m "describe_changes"
   ```

2. **Apply migrations to the database**:
   ```bash
   alembic upgrade head
   ```

3. **Roll back the last migration**:
   ```bash
   alembic downgrade -1
   ```

---

## How to Run Tests

Tests are automated with Pytest, testing `/health`, `/health/db`, database connection verification, and configuration isolation:

```bash
cd backend
pytest
```

To run with verbose output:
```bash
pytest -v
```
