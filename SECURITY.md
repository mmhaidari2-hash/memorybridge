# Security Policy

MemoryBridge handles application memory, workspace credentials, and billing entitlement, so security issues should be treated as high priority.

## Supported versions

The current commercial-foundation branch is `v0.4`. Earlier experimental code, including the `v0.2` secure-foundation snapshot, should not be treated as the current security model.

## Reporting a vulnerability

Please do not publish a working exploit, production credential, encryption key, Stripe secret, webhook signing secret, workspace API key, or private user/memory data in a public issue.

Until a dedicated private vulnerability-reporting channel is configured, repository owners should enable GitHub Private Vulnerability Reporting before a public production launch.

## Security model (v0.4)

MemoryBridge v0.4 provides:

- **Tenant and workspace isolation.** Memory records, API keys, and usage events are scoped to the authenticated workspace and its tenant. A workspace key cannot list, revoke, recall, or update another workspace's resources.
- **API-key hashing and lifecycle.** Workspace API keys are stored as SHA-256 hashes plus a short display prefix. Plaintext `mbs_...` keys are returned only at creation time (API or operator bootstrap). Revoked keys cannot authenticate. Legacy `SERVICE_API_KEYS` remain for transition and cannot manage workspace keys, account status, or checkout.
- **Encrypted memory persistence.** Memory summaries are encrypted with AES-256-GCM and a fresh random nonce before database storage. User and session tokens are stored as SHA-256 digests, not plaintext.
- **Quota enforcement.** Billable workspace operations are metered as persisted usage events. Monthly limits follow the tenant's current plan. Excess traffic is rejected with HTTP 429 and is not recorded as usage.
- **Stripe webhook signature verification.** `POST /v1/billing/webhook` requires a `Stripe-Signature` header. The raw body is verified with `STRIPE_WEBHOOK_SECRET` before any event is trusted. Missing or invalid signatures return HTTP 400 and write nothing.
- **Entitlement source of truth.** A browser redirect to the billing success URL never grants a paid plan. Paid entitlement is derived only from verified server-side subscription state after a signed webhook. `checkout.session.completed` may store Stripe identifiers; only `customer.subscription.created` / `updated` with a trusted `pro`/`team` plan and `active`/`trialing` status grant paid access. Invalid or malformed billing events fail closed and roll back partial database state. Duplicate provider event IDs are idempotent.
- **Fail-closed production configuration.** Customer-facing deployments must set `APP_ENV=production`. In that mode the process refuses to start with missing/placeholder secrets, non-PostgreSQL `DATABASE_URL`, non-HTTPS CORS origins or billing redirects, wildcard CORS, or Stripe credentials that do not match `BILLING_MODE`.
- **Secret and log hygiene.** Request logs include method, path, status, duration, and a bounded request ID. They exclude request bodies, query strings, API keys, user/session tokens, Stripe secrets, webhook signatures, checkout URLs/session IDs, encryption keys, and memory content.
- **CORS policy.** `CORS_ALLOWED_ORIGINS` must list explicit origins. A wildcard `*` is rejected at startup. Same-origin `/app` static pages avoid CORS on the critical customer path.
- **PWA and loopback drafts.** The `/app` service worker is scoped to `/app/` and never caches `/v1`. Local IndexedDB drafts and `scripts/loopback_bridge.py` use the same manual-record contract. The CLI binds only to loopback and cannot grant paid entitlement.
- **Test / Live Stripe separation.** The application uses the same variable names in both modes. `BILLING_MODE=test` requires `sk_test_...`; `BILLING_MODE=live` requires `sk_live_...`. Test and Live Price IDs and webhook secrets must not be mixed. Staging remains Test Mode until the sandbox gate passes.

MemoryBridge v0.4 does **not** provide:

- zero-knowledge or end-to-end encryption;
- protection from an attacker who has both the database contents and the live server encryption key;
- automatic encryption-key rotation;
- public self-service signup or anonymous workspace provisioning;
- enterprise identity federation or fine-grained RBAC;
- a compliance certification;
- globally distributed rate limiting unless Redis is explicitly selected and reachable. Local/development uses process memory and ignores a leftover REDIS_URL.

## Secret handling

- Never commit `.env` files, `ENCRYPTION_KEY`, database credentials, workspace API keys, user/session tokens, Stripe secret keys, webhook signing secrets, or checkout session secrets.
- Use a secrets manager or protected platform environment variables in production.
- Treat workspace API keys and user/session tokens returned by the API as bearer secrets. Copy bootstrap output once; do not paste it into GitHub, logs, tickets, screenshots, or committed files.
- Avoid logging request bodies, decrypted memory content, Stripe signatures, or checkout URLs.
- Back up encrypted data and encryption keys separately and protect access to both.

## Deployment expectations

Production and customer-facing staging should use HTTPS, a secured PostgreSQL service, `alembic upgrade head` as an explicit pre-deploy step (application startup does not migrate), network restrictions, least-privilege database credentials, monitored backups, and platform-level secret protection. Never weaken `APP_ENV=production` checks to force startup.

## Dependency and change policy

Security-sensitive changes should be made through a branch and pull request, with CI passing before merge. Schema changes should use Alembic migrations rather than manual production-table edits.
