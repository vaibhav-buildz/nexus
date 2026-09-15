# NEXUS Authentication & Identity Architecture

This document details the security model, token lifecycles, and architectural decisions behind the Phase 1 Authentication and Identity Foundation in NEXUS.

---

## 1. Security Architecture & Threat Model

### Password Hashing: Argon2id
- **Algorithm**: Argon2id (`v=19`, `m=65536` [64 MiB], `t=3`, `p=4`).
- **Rationale**: Argon2id is the winner of the Password Hashing Competition (PHC) and OWASP's primary recommendation. It combines Argon2d's resistance to GPU/ASIC side-channel cracking with Argon2i's resistance to cache-timing attacks.
- **Timing Attacks**: The login endpoint runs verification against a dummy hash when an email address does not exist, keeping execution latency consistent and preventing username enumeration.

---

## 2. Token Lifecycle & Session Model

```
   [ Client ]               [ NEXUS API ]             [ PostgreSQL ]
       │                          │                          │
       │── POST /auth/login ─────>│                          │
       │                          │── Verify Argon2id ──────>│
       │                          │<─ Valid User ────────────│
       │                          │                          │
       │                          │── Store Session ────────>│
       │                          │   (token_hash, family_id)│
       │<─ {access, refresh} ─────│                          │
       │                          │                          │
       │── GET /auth/me ─────────>│                          │
       │   (Bearer Access Token)  │ (Verify JWT signature)   │
       │<─ 200 OK (User Profile) ─│                          │
       │                          │                          │
       │── POST /auth/refresh ───>│                          │
       │   (Old Refresh Token)    │── Query Session Hash ───>│
       │                          │<─ Session Record ────────│
       │                          │                          │
       │                          │── Revoke Old Session ───>│
       │                          │── Create New Session ───>│
       │                          │   (same family_id)       │
       │<─ {new_acc, new_ref} ────│                          │
```

### Access Tokens (Short-Lived JWT)
- **Lifetime**: 15 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- **Signature**: HMAC-SHA256 (`HS256`) signed with `JWT_SECRET_KEY`.
- **Claims**:
  - `sub`: User UUID string
  - `iat`: Issued-at Unix timestamp
  - `exp`: Expiration Unix timestamp
  - `iss`: Issuer (`NEXUS`)
  - `type`: `"access"`
- **Storage**: In-memory only on the client.

### Refresh Tokens & Cryptographic Hashing
- **Generation**: Cryptographically secure 256-bit URL-safe random string (`secrets.token_urlsafe(32)`).
- **Database Storage**: The raw token is **never stored**. Only its SHA-256 digest (`token_hash`) is persisted. If the database is compromised, attackers cannot use the stored hashes as valid refresh tokens.
- **Lifetime**: 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`).

---

## 3. Refresh Token Rotation & Reuse Detection

To prevent refresh token theft from becoming persistent access, NEXUS enforces **single-use refresh token rotation with token family tracking**:

1. **Rotation**: Every time a refresh token is exchanged via `POST /api/v1/auth/refresh`, the presented token is immediately marked as revoked (`revoked_at = now`), and a new refresh token is issued under the same `family_id`.
2. **Reuse Detection**:
   - If an attacker intercepts a refresh token and uses it *after* the legitimate client has already rotated it (or if the legitimate client uses it after an attacker rotated it), the server detects that an **already revoked session is being presented**.
   - **Automatic Containment**: The system immediately revokes **all sessions belonging to that `family_id`**, locking out both the attacker and alerting the user.
   - The endpoint returns HTTP 401 with `TOKEN_REUSE_DETECTED`.

---

## 4. Email Verification Abstraction

- **Design**: The core engine generates a 256-bit random verification token and stores its SHA-256 hash in `email_verification_tokens` table.
- **Providers**:
  - `ConsoleEmailService` (default): Logs verification tokens directly to application logs for zero-friction local development without external dependencies or credit cards.
  - `MockEmailService`: Used in automated test suites for deterministic in-memory verification.
  - Pluggable interface (`BaseEmailService`) prepared for production SMTP/SendGrid/Postmark integration.

---

## 5. API Endpoints Reference

| Method | Endpoint | Status | Auth Required | Description |
| :--- | :--- | :---: | :---: | :--- |
| `POST` | `/api/v1/auth/register` | `201 Created` | No | Registers user with Argon2id hash & issues verification token |
| `POST` | `/api/v1/auth/login` | `200 OK` | No | Validates credentials; returns access + refresh token pair |
| `POST` | `/api/v1/auth/refresh` | `200 OK` | No | Rotates refresh token and detects token reuse |
| `POST` | `/api/v1/auth/logout` | `200 OK` | No | Revokes refresh token session |
| `GET` | `/api/v1/auth/me` | `200 OK` | Yes (Bearer) | Returns authenticated user profile |
| `POST` | `/api/v1/auth/verify-email` | `200 OK` | No | Confirms user email address |
