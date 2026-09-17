# MemoryBridge

MemoryBridge is a self-hosted, multi-tenant persistence service for storing encrypted AI application memory.

It is designed for LLM wrappers, agents, assistants, and other applications that need durable user/session context without storing memory summaries as plaintext in the database.

## Current status

MemoryBridge **v0.4** adds the commercial foundation required to sell into AI companies:

- tenant / workspace isolation
- durable service API keys with create + revoke
- encryption key versioning + AAD-bound AES-256-GCM
- peppered credential hashing
- append-only audit events
- Prometheus metrics
- memory delete + metadata list
- request body size limits

## Security model

- Memory summaries are encrypted with AES-256-GCM before database storage.
- Ciphertext is bound with AAD to `tenant_id` + `user_id` so records cannot be transplanted across identities.
- `user_token` and `session_token` values are never stored in plaintext; peppered HMAC-SHA256 digests are stored for lookup.
- Each memory record belongs to a tenant and an internal user ID.
- All `/v1` application routes require a valid service API key in `X-MemoryBridge-Key`.
- Admin routes require `X-MemoryBridge-Admin-Key`.
- Authenticated keys are rate-limited independently.
- Request logging excludes bodies, query strings, API keys, tokens, and memory content.

### Important terminology

MemoryBridge is **not currently a zero-knowledge system**. The server receives the plaintext summary and has access to the encryption keyring in order to encrypt/decrypt memory.

## API

Base version prefix: `/v1`

### Application (service key)

- `POST /v1/auth/token` — create a user credential inside the caller's tenant
- `POST /v1/memory/store` — store an encrypted memory and receive a session token
- `POST /v1/memory/recall` — recall one session using user + session credentials
- `PUT /v1/memory/update` — update one session
- `POST /v1/memory/delete` — delete one session
- `POST /v1/memory/list` — list session metadata only (never returns summaries)

### Admin (admin key)

- `POST /v1/admin/tenants` — create a tenant
- `POST /v1/admin/tenants/{id}/keys` — issue a durable service API key (plaintext returned once)
- `POST /v1/admin/keys/{id}/revoke` — revoke a durable key
- `POST /v1/admin/tenants/{id}/suspend` — suspend a tenant

### Ops

- `GET /health` — liveness
- `GET /ready` — database readiness
- `GET /metrics` — Prometheus counters

Application requests must include:

```text
X-MemoryBridge-Key: <service-api-key>
```

Admin requests must include:

```text
X-MemoryBridge-Admin-Key: <admin-api-key>
```

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
```

Generate secrets:

```bash
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
python3 -c "import secrets; print('mbs_' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('mba_' + secrets.token_urlsafe(32))"
```

Set at minimum:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/memorybridge
ENCRYPTION_KEY=<generated-base64-key>
SERVICE_API_KEYS=<generated-service-api-key>
ADMIN_API_KEY=<generated-admin-api-key>
TOKEN_HASH_PEPPER=<generated-base64-pepper>
```

For key rotation:

```text
ENCRYPTION_KEYS=1:<old-key>,2:<new-key>
ENCRYPTION_ACTIVE_VERSION=2
```

Never commit production credentials or encryption keys.

### 2. Install

```bash
python3 -m venv .venv
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

## Python client

```python
from memorybridge_client import MemoryBridgeAdminClient, MemoryBridgeClient

admin = MemoryBridgeAdminClient("http://localhost:8000", admin_api_key="mba_...")
tenant = admin.create_tenant("Acme AI", "acme-ai")
key = admin.create_api_key(tenant["id"], "production")

mb = MemoryBridgeClient("http://localhost:8000", service_api_key=key["api_key"])

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

mb.update(user_token, session_token, summary="Concise Farsi docs preferred.", stage="active")
print(mb.list_sessions(user_token))
mb.delete(user_token, session_token)
```

Treat service, admin, user, and session credentials as secrets. Losing a session token means the current secure API cannot recover that token from the database because only its hash is stored. `memory/list` therefore returns metadata IDs, not recoverable session tokens.

## How you make money

MemoryBridge ships a billing layer:

| Plan | Price | Monthly ops | Max memories |
|------|-------|-------------|--------------|
| Free | $0 | 1,000 | 100 |
| Starter | $49 | 50,000 | 10,000 |
| Growth | $199 | 500,000 | 100,000 |

- Over-quota API calls return **HTTP 402** with an upgrade hint
- `GET /v1/billing/status` shows usage for the caller's tenant
- `POST /v1/billing/checkout` opens Stripe Checkout (when configured)
- `POST /v1/admin/tenants/{id}/plan` assigns a plan after offline payment
- `POST /v1/billing/webhook` activates paid plans from Stripe events

Sales flow:

1. Create tenant + API key for the customer
2. They start on Free and hit limits
3. They pay via Stripe checkout **or** bank transfer + you assign `starter`/`growth`
4. Quotas unlock automatically

## Multi-tenant sales model

1. Create one tenant per customer company.
2. Issue one or more durable service keys per environment (prod/stage).
3. Customers never share keys across tenants.
4. Revoke a key or suspend the tenant when access must stop immediately.
5. Keep env `SERVICE_API_KEYS` for bootstrap/break-glass on the default tenant only.

## Rate limiting

The current limiter is process-local and keyed by authenticated service/admin identity. Defaults are 120 requests per 60 seconds. A `429` response includes `Retry-After`.

For horizontal scaling, replace the process-local limiter with Redis (or equivalent) before treating limits as globally enforced.

## Observability

- Responses include `X-Request-ID`.
- HTTP logs contain only method, path, status, duration, and request ID.
- Audit events record action/outcome/actor/resource without secrets or memory bodies.
- `/metrics` exposes `memorybridge_requests_total`.

## Tests

```bash
pytest -q
```

Coverage includes encryption AAD binding, key versioning, peppered hashing, service auth, tenant isolation, key revocation, tenant suspension, rate limiting, security headers, readiness, privacy-safe observability, and end-to-end memory flows.

## Database changes

Schema changes are managed with Alembic. Do not mutate production tables manually when a migration should be used.

### Breaking notes from v0.3 → v0.4

- Users and memories are tenant-scoped.
- Credential hashing is now peppered HMAC-SHA256 (`TOKEN_HASH_PEPPER`). Existing v0.3 token hashes are not compatible; re-issue user/session tokens after upgrade.
- Encryption helpers require tenant/user AAD; stored rows gain `key_version`.
- Prefer durable DB API keys for customers; env keys remain bootstrap-only.

## Deployment notes

For production deployments:

- use managed/secured PostgreSQL;
- store encryption keys, pepper, and API keys in a secrets manager;
- terminate TLS at a trusted reverse proxy and expose HTTPS only;
- create a tenant + durable key per customer;
- rotate/revoke keys on compromise;
- back up the database and separately protect the encryption keyring;
- run the supplied container as its non-root user;
- use `/health` for liveness and `/ready` for traffic readiness;
- move rate-limit state to Redis before horizontal scaling.

## What v0.4 does not claim

This release does not claim zero-knowledge encryption, end-to-end encryption, compliance certification, automatic historical re-encryption, multi-region durability, distributed rate limiting, or enterprise SSO. Those require explicit follow-on design.

## Roadmap

1. distributed rate limiting and usage metering
2. online re-encryption / key retirement tooling
3. durable admin accounts with scoped roles
4. audit export and SIEM hooks
5. packaging / SDK ergonomics
6. hosted deployment and commercial billing foundations

## License

No open-source license has been selected yet. Until a license is added, copyright remains with the repository owner and reuse rights are not automatically granted.
