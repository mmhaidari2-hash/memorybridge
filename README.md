# MemoryBridge

MemoryBridge is a lightweight, self-hosted persistence service for storing encrypted AI application memory.

It is designed for LLM wrappers, agents, assistants, and other applications that need durable user/session context without storing memory summaries as plaintext in the database.

## Current status

MemoryBridge v0.2 is a secure-foundation release candidate. The API, credential model, database schema, migrations, tests, and CI have been rebuilt before further product features are added.

## Security model

- Memory summaries are encrypted with AES-256-GCM before database storage.
- `user_token` and `session_token` values are not stored in plaintext; SHA-256 digests are stored for lookup.
- Each memory record belongs to an internal user ID, reducing accidental cross-user access paths.
- `ENCRYPTION_KEY` and `DATABASE_URL` are mandatory runtime configuration. The service fails closed when they are missing or invalid.
- The API requires both user and session credentials for memory recall/update.

### Important terminology

MemoryBridge is **not currently a zero-knowledge system**. The server receives the plaintext summary and has access to the encryption key in order to encrypt/decrypt memory. A future client-side encryption mode could provide a different trust model.

## API

Base version prefix: `/v1`

- `POST /v1/auth/token` — create a user credential
- `POST /v1/memory/store` — store an encrypted memory and receive a session token
- `POST /v1/memory/recall` — recall one session using user + session credentials
- `PUT /v1/memory/update` — update one session
- `GET /health` — health check

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

Set:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/memorybridge
ENCRYPTION_KEY=<generated-base64-key>
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
```

## Python client

```python
from memorybridge_client import MemoryBridgeClient

mb = MemoryBridgeClient("http://localhost:8000")

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

Treat returned user/session tokens as secrets. Losing a session token means the current secure API cannot recover that token from the database because only its hash is stored.

## Tests

```bash
pytest -q
```

The test suite covers encryption round trips, nonce freshness, credential hashing, end-to-end API flow, invalid credentials, and cross-user session isolation.

## Database changes

Schema changes are managed with Alembic. Do not mutate production tables manually when a migration should be used.

## Deployment notes

For production deployments:

- use a managed PostgreSQL instance or properly secured PostgreSQL deployment;
- store `ENCRYPTION_KEY` in a secrets manager or protected platform environment variable;
- terminate TLS at a trusted reverse proxy/platform and expose the API over HTTPS only;
- rotate credentials when compromised;
- restrict network/database access to the minimum required;
- back up the database and separately protect the encryption key.

## What v0.2 does not claim

This release does not claim zero-knowledge encryption, end-to-end encryption, compliance certification, automatic key rotation, multi-region durability, or enterprise-grade identity management. Those require explicit design and verification rather than marketing labels.

## Roadmap

Near-term priorities after the secure foundation is merged:

1. production deployment hardening;
2. rate limiting and abuse controls;
3. API-key / service-account authentication for application clients;
4. structured tenant/workspace isolation;
5. observability and audit events without logging plaintext memory;
6. key rotation/versioning;
7. packaging and SDK ergonomics;
8. commercial plans and hosted deployment options.

## License

No open-source license has been selected yet. Until a license is added, copyright remains with the repository owner and reuse rights are not automatically granted.
