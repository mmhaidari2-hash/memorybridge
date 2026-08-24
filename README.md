# MemoryBridge

MemoryBridge is a lightweight, self-hosted persistence service for storing encrypted AI application memory.

It is designed for LLM wrappers, agents, assistants, and other applications that need durable user/session context without storing memory summaries as plaintext in the database.

## Current status

MemoryBridge v0.3 is in production-hardening review. The secure foundation from v0.2 is now extended with service-level API authentication, per-key rate limiting, readiness checks, security headers, privacy-safe request logging, and a hardened container runtime.

## Security model

- Memory summaries are encrypted with AES-256-GCM before database storage.
- `user_token` and `session_token` values are not stored in plaintext; SHA-256 digests are stored for lookup.
- Each memory record belongs to an internal user ID, reducing accidental cross-user access paths.
- `ENCRYPTION_KEY`, `DATABASE_URL`, and `SERVICE_API_KEYS` are mandatory runtime configuration where applicable. Security-sensitive configuration fails closed.
- All `/v1` routes require a valid service API key in `X-MemoryBridge-Key`.
- Authenticated service keys are rate-limited independently.
- Memory recall/update additionally require the correct user and session credentials.
- Request logging excludes request bodies, query strings, API keys, user/session tokens, and memory content.

### Important terminology

MemoryBridge is **not currently a zero-knowledge system**. The server receives the plaintext summary and has access to the encryption key in order to encrypt/decrypt memory. A future client-side encryption mode could provide a different trust model.

## API

Base version prefix: `/v1`

- `POST /v1/auth/token` — create a user credential
- `POST /v1/memory/store` — store an encrypted memory and receive a session token
- `POST /v1/memory/recall` — recall one session using user + session credentials
- `PUT /v1/memory/update` — update one session
- `GET /health` — liveness check
- `GET /ready` — database readiness check

All `/v1` requests must include:

```text
X-MemoryBridge-Key: <service-api-key>
```

## Quick start

### 1. Configure environment

Copy the example file and set real values:

```bash
cp .env.example .env
```

Generate a 32-byte AES key encoded as Base64:

```bash
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Generate a service API key:

```bash
python -c "import secrets; print('mbs_' + secrets.token_urlsafe(32))"
```

Set:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/memorybridge
ENCRYPTION_KEY=<generated-base64-key>
SERVICE_API_KEYS=<generated-service-api-key>
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

Never commit production credentials or encryption keys.

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Apply database migrations

```bash
alembic upgrade head
```

### 4. Run the API

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Check:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## Python client

```python
from memorybridge_client import MemoryBridgeClient

mb = MemoryBridgeClient(
    "http://localhost:8000",
    service_api_key="mbs_your_service_key",
)

user = mb.create_user("Mahdi")
user_token = user["user_token"]

stored = mb.store(
    user_token,
    summary="User prefers technical documentation in Farsi.",
    stage="onboarding",
)
session_token = stored["session_token"]

memory = mb.recall(user_token, session_token)
print(memory["summary"])

updated = mb.update(
    user_token,
    session_token,
    summary="User prefers concise technical documentation in Farsi.",
    stage="active",
)
```

Treat service, user, and session credentials as secrets. Losing a session token means the current secure API cannot recover that token from the database because only its hash is stored.

## Rate limiting

The current limiter is process-local and keyed by authenticated service API key. Defaults are 120 requests per 60 seconds. A `429` response includes `Retry-After`.

For horizontal scaling across multiple application instances, replace the process-local limiter with a distributed backend such as Redis before treating limits as globally enforced.

## Observability

Responses include `X-Request-ID`. Clients may supply an `X-Request-ID` for correlation, or the service generates one.

Request logs contain only method, path, status code, duration, and request ID. They intentionally do not log request bodies, query strings, memory summaries, API keys, user tokens, or session tokens.

## Tests

```bash
pytest -q
```

The suite covers encryption, credential hashing, service authentication, rate limiting, security headers, readiness, privacy-safe observability, end-to-end API flow, invalid credentials, and cross-user session isolation.

## Database changes

Schema changes are managed with Alembic. Do not mutate production tables manually when a migration should be used.

## Deployment notes

For production deployments:

- use a managed PostgreSQL instance or properly secured PostgreSQL deployment;
- store `ENCRYPTION_KEY` and service API keys in a secrets manager or protected platform environment variables;
- terminate TLS at a trusted reverse proxy/platform and expose the API over HTTPS only;
- rotate credentials when compromised;
- restrict network/database access to the minimum required;
- back up the database and separately protect the encryption key;
- run the supplied container as its non-root user;
- use `/health` for liveness and `/ready` for traffic readiness;
- move rate-limit state to Redis or another distributed store before horizontal scaling.

## What v0.3 does not claim

This release does not claim zero-knowledge encryption, end-to-end encryption, compliance certification, automatic key rotation, multi-region durability, distributed rate limiting, or enterprise-grade identity management. Those require explicit design and verification rather than marketing labels.

## Roadmap

Near-term priorities after v0.3 production hardening:

1. structured tenant/workspace isolation;
2. durable service-account/API-key records with revocation and rotation;
3. distributed rate limiting and usage metering;
4. encryption-key rotation/versioning;
5. audit events and operational metrics;
6. packaging and SDK ergonomics;
7. hosted deployment and commercial billing foundations.

## License

No open-source license has been selected yet. Until a license is added, copyright remains with the repository owner and reuse rights are not automatically granted.
