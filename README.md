# MemoryBridge

MemoryBridge is a secure persistence API for AI applications that need durable user and session memory without storing memory summaries as plaintext in the database.

It is built for LLM applications, agents, assistants, and developer products that need a small, auditable memory layer with workspace isolation, API-key authentication, usage metering, plan quotas, and subscription-billing foundations.

## v0.4 commercial foundation

The current development branch adds the commercial control plane on top of the hardened memory API:

- tenant and workspace isolation;
- database-backed workspace API keys with revocation;
- usage-event metering;
- Free / Pro / Team quota enforcement;
- account/usage status API;
- Stripe Checkout and signed webhook foundations;
- webhook-driven subscription entitlement with idempotency;
- Python client helpers for memory, account, key management, and checkout.

Stripe billing remains in Test Mode until the sandbox release gate in `docs/STRIPE_SANDBOX_RUNBOOK.md` is completed. A successful browser redirect never grants a paid plan; only a verified subscription webhook can change entitlement.

## Security model

- Memory summaries are encrypted with AES-256-GCM before database storage.
- User and session tokens are stored as SHA-256 digests rather than plaintext.
- Workspace API keys are stored as hashes; newly generated plaintext keys are returned only at creation time.
- Memory access is scoped to the authenticated workspace and user/session credentials.
- Security-sensitive runtime configuration fails closed.
- Request logging excludes request bodies, query strings, API keys, user/session tokens, and memory content.
- Stripe webhook signatures are verified before subscription state is trusted.
- Duplicate billing events are processed idempotently.

MemoryBridge is **not currently a zero-knowledge or end-to-end encrypted system**. The server receives plaintext memory content and has access to the encryption key in order to encrypt and decrypt it.

## Workspace access (read this before onboarding)

These three paths are different. Do not conflate them:

1. **Customer onboarding (exists).** `/app/onboarding.html` verifies an already-provisioned workspace API key, then requires a real store/recall round-trip before the dashboard. It does not create a tenant, workspace, or first API key.
2. **Operator bootstrap (exists).** The first Staging or local workspace is created by an operator after migrations, using `scripts/bootstrap_workspace.py` with explicit tenant and workspace names. The CLI prints the plaintext `mbs_...` key once. There is no public HTTP provisioning endpoint.
3. **Public self-service signup (does not exist).** MemoryBridge does not currently offer public signup or browser-based workspace creation.

## Five-minute developer path

Configure the service from `.env.example`, apply migrations, start the API, then obtain a workspace API key from operator bootstrap (or a later key created by an already-authenticated workspace). Onboarding only verifies that key.

### 1. Start the service

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/bootstrap_workspace.py --tenant-name "Local Dev" --workspace-name "Default"
uvicorn main:app --host 0.0.0.0 --port 8000
```

Application startup does not run migrations. `alembic upgrade head` is a required operator step before the API can use tenant, workspace, billing, or usage tables.

The bootstrap CLI prints the workspace API key once. Do not paste that value into GitHub, logs, tickets, screenshots, or committed files.

Verify readiness:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Never commit production credentials, Stripe secrets, API keys, database credentials, or encryption keys.

### 2. Connect with Python

```python
from memorybridge_client import MemoryBridgeClient

mb = MemoryBridgeClient(
    "http://localhost:8000",
    service_api_key="mbs_your_workspace_key",
)
```

### 3. Create an application user

```python
user = mb.create_user("Demo User")
user_token = user["user_token"]
```

The user token is a credential. Store it securely; MemoryBridge stores only its digest.

### 4. Store and recall memory

```python
stored = mb.store(
    user_token,
    summary="The user prefers concise answers.",
    stage="onboarding",
)

session_token = stored["session_token"]
memory = mb.recall(user_token, session_token)
print(memory["summary"])
```

Update the same memory session when needed:

```python
mb.update(
    user_token,
    session_token,
    summary="The user prefers concise technical answers.",
    stage="active",
)
```

### 5. Inspect plan and usage

```python
status = mb.account_status()
print(status["plan"])
print(status["usage"])
```

The server, not the SDK, is authoritative for quota enforcement.

## Commercial API surface

All workspace operations authenticate with:

```text
X-MemoryBridge-Key: <workspace-api-key>
```

Core memory endpoints:

```text
POST /v1/auth/token
POST /v1/memory/store
POST /v1/memory/recall
PUT  /v1/memory/update
```

Workspace control-plane endpoints:

```text
GET    /v1/account/status
POST   /v1/api-keys
GET    /v1/api-keys
DELETE /v1/api-keys/{key_id}
POST   /v1/billing/checkout
```

Billing webhook endpoint:

```text
POST /v1/billing/webhook
```

The webhook is provider-facing and uses Stripe signature verification rather than workspace-key authentication.

## API key lifecycle

Create another key for the same workspace:

```python
created = mb.create_api_key("Production")
new_key = created["api_key"]  # returned once
```

List metadata without exposing plaintext secrets:

```python
keys = mb.list_api_keys()
```

Revoke a key:

```python
mb.revoke_api_key(created["id"])
```

A revoked key must no longer authenticate.

## Upgrade flow

When Stripe Test Mode is configured, an authenticated workspace can request a trusted server-side checkout:

```python
checkout = mb.create_checkout("pro")
print(checkout["checkout_url"])
```

The caller supplies only a supported plan name. Stripe Price IDs are selected from protected server configuration, not accepted from the caller.

Important entitlement rule:

```text
Checkout success redirect != paid entitlement
Verified active/trialing subscription webhook == paid entitlement
```

Cancellation or another non-active subscription state removes paid entitlement according to the verified lifecycle event.

See `docs/STRIPE_SANDBOX_RUNBOOK.md` before enabling Live Mode.

## Plans and quotas

The v0.4 branch currently defines Free, Pro, and Team monthly event limits in the server quota module. These are engineering defaults while pricing is being validated; they are not a permanent public pricing promise.

When a tenant reaches its monthly event quota, billable operations fail with HTTP `429` and no rejected usage event is added.

## Observability and operational boundaries

Responses include `X-Request-ID`. Logs contain method, path, status code, duration, and request ID while intentionally excluding sensitive request data.

The request-rate limiter is process-local in development and ignores a leftover `REDIS_URL`. You do not need to unset that variable for local work. Redis is used only when `RATE_LIMIT_BACKEND=redis` or when `APP_ENV=production` and `REDIS_URL` is set. If Redis is opted into locally but unreachable, the limiter falls back to memory. Production fails closed if `REDIS_URL` is set but Redis cannot be reached. Usage quota enforcement is backed by persisted usage events, but scaling and concurrency behavior must still be load-tested before high-volume production claims are made.

## Tests

Run:

```bash
pytest -q
```

The suite covers the core encrypted-memory flow plus service authentication, tenant/workspace isolation, usage metering, quota boundaries, API-key lifecycle, checkout session creation, billing entitlement security, webhook idempotency, operator workspace bootstrap, Python client behavior, PWA install contracts, extension pairing, and local manual-record export/import.

## PWA, companion extension, and local drafts

`/app` is installable as a same-origin PWA. The service worker is scoped to `/app/` and never caches `/v1/` API traffic. Local manual drafts live in IndexedDB and can be exported or imported as JSON or SQLite-compatible SQL. They are not server memory and cannot grant paid entitlement.

The unpacked Chrome MV3 companion in `extension/` pairs from Dashboard and can send a draft into the open records page. It stores only the app origin, not the workspace API key.

## Deployment gate

Before accepting real money:

- apply all Alembic migrations;
- keep secrets only in protected deployment configuration;
- expose the service over HTTPS;
- complete the Stripe sandbox runbook end to end;
- prove Free -> paid -> Free lifecycle behavior on the deployed environment;
- confirm invalid and duplicate webhooks behave safely;
- verify quota follows entitlement changes;
- keep CI green;
- perform a low-risk Live Mode transaction only after the sandbox gate passes.

## What MemoryBridge does not claim

MemoryBridge does not currently claim zero-knowledge encryption, end-to-end encryption, compliance certification, multi-region durability, globally distributed rate limiting, enterprise SSO, or automatic encryption-key rotation. Those capabilities require explicit implementation and evidence before they should appear in product claims.

## Near-term path to market

The commercial Landing, Onboarding, and Dashboard pages already exist. Onboarding verifies an operator-provisioned workspace key; it is not public signup.

1. Deploy Staging, apply migrations, and bootstrap the first workspace with the operator CLI.
2. Pass deployed Stripe Test Mode end-to-end, including a genuine signed webhook.
3. Validate the five-minute integration path with external developers using a provisioned workspace key.
4. Publish clear pricing only after cost and willingness-to-pay validation.
5. Recruit a small private beta and measure activation, repeated use, conversion, and retention.
6. Enable Live Mode only after the commercial release gate passes.

Public self-service workspace provisioning is future work and is not available in this branch.

## License

No open-source license has been selected yet. Until a license is added, copyright remains with the repository owner and reuse rights are not automatically granted.
