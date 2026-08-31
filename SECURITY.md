# Security Policy

MemoryBridge handles application memory, workspace credentials, and subscription entitlement, so security issues should be treated as high priority.

## Supported versions

The current commercial development branch is `v0.4-commercial-foundation`. The previous secure-foundation candidate was `v0.2`. Earlier experimental code should not be treated as production-ready. v0.4 is not a compliance-certified release.

## Reporting a vulnerability

Please do not publish a working exploit, production credential, encryption key, Stripe secret, webhook signature, checkout session, API key, or private user data in a public issue.

Until a dedicated private vulnerability-reporting channel is configured, repository owners should enable GitHub Private Vulnerability Reporting before a public production launch.

## Security boundaries

MemoryBridge v0.4 currently provides:

- tenant and workspace isolation for database-backed workspace API keys;
- SHA-256 hashing of workspace API keys, with only a short display prefix stored alongside the hash;
- API-key revocation (`is_active=false`) so a revoked key must fail authentication;
- AES-256-GCM encryption of memory summaries before database persistence, with a fresh random nonce per encryption operation;
- SHA-256 hashing of user and session tokens rather than plaintext storage;
- ownership checks that bind memory records to the authenticated workspace and internal user identifier;
- persisted usage-event metering and monthly plan quota enforcement for Free / Pro / Team;
- Stripe webhook signature verification before any billing event is trusted;
- webhook idempotency keyed on Stripe event IDs;
- fail-closed rollback when a supported webhook cannot be applied safely;
- server-side tenant `plan` / `subscription_status` as the entitlement source of truth;
- production runtime validation that fails closed on missing/placeholder secrets, non-HTTPS browser origins or billing redirects, and Stripe Test/Live credential mismatch;
- explicit CORS allow-lists (wildcard origins are rejected);
- request logging that records method, path, status, duration, and a correlation ID while excluding bodies, query strings, API keys, user/session tokens, Stripe signatures, checkout URLs, and memory content.

MemoryBridge v0.4 does **not** provide:

- zero-knowledge or end-to-end encryption;
- protection from an attacker who has both the database contents and the live server encryption key;
- automatic encryption-key rotation;
- a public self-service signup or tenant-provisioning HTTP endpoint;
- enterprise identity federation or fine-grained RBAC;
- a compliance certification;
- globally distributed rate limiting (the current limiter is process-local);
- a guarantee against denial-of-service.

## Tenant and workspace isolation

A database-backed workspace API key authenticates to exactly one workspace and its parent tenant. Memory store/recall/update and account/key/billing control-plane operations use that workspace context. A key from workspace B cannot read or update workspace A memory even if user/session tokens are presented. Legacy environment keys (`SERVICE_API_KEYS`) may still authenticate some memory routes during transition, but they have no tenant/workspace context and cannot create Checkout Sessions or manage workspace API keys.

## Workspace API key hashing and lifecycle

Newly generated keys use cryptographic randomness in the `mbs_...` format. The database stores only the SHA-256 hash, a short display prefix, and normal metadata. Plaintext is returned only at creation time (API create-key response or operator bootstrap CLI after a successful commit). Revoked or inactive keys, and keys whose tenant is not `active`, are rejected.

## Encrypted memory persistence

Memory summaries are encrypted with AES-256-GCM before they are written. The server receives plaintext content from the client and uses the deployment `ENCRYPTION_KEY` to encrypt and decrypt. This is **not** zero-knowledge and **not** end-to-end encryption.

## User and session credential hashing

User tokens and session tokens returned by the API are bearer secrets. MemoryBridge stores only SHA-256 digests.

## Usage quota enforcement

Billable workspace operations are metered as persisted usage events. When a tenant reaches its monthly plan limit, further billable operations fail with HTTP `429` and the rejected event is not recorded.

## Stripe billing security

- Checkout Price IDs come from server environment variables (`STRIPE_PRICE_PRO`, `STRIPE_PRICE_TEAM`), not from the caller.
- Checkout success and cancel URLs come from server environment variables, not from the caller.
- Creating a Checkout Session does not change `tenant.plan` and does not create paid entitlement.
- A browser redirect to `?billing=success` is **not** proof of payment.
- Paid entitlement changes only after a verified Stripe subscription lifecycle webhook for a trusted `pro`/`team` plan in `active` or `trialing` status.
- `checkout.session.completed` may store Stripe customer/subscription identifiers; it must not grant a paid plan.
- Webhook requests without a valid Stripe signature are rejected with HTTP 400 and must not write billing or entitlement rows.
- Duplicate Stripe event IDs are applied once (`BillingEvent.provider_event_id` uniqueness).
- Invalid plan metadata or other application-level webhook validation failures roll back the event row and tenant mutations.

## Test vs Live Stripe

`BILLING_MODE` selects the Stripe namespace. The application uses the same variable names in both modes; there are no `STRIPE_TEST_*` aliases. Production validation requires `sk_test_` when `BILLING_MODE=test` and `sk_live_` when `BILLING_MODE=live`. Test Mode identifiers must never be reused in Live Mode.

## Production runtime validation

Customer-facing deployments must set `APP_ENV=production`. In that mode the process refuses to start with placeholder/missing database or encryption configuration, non-HTTPS CORS origins or billing redirects, incomplete Stripe configuration, or Test/Live credential mismatch.

## CORS

`CORS_ALLOWED_ORIGINS` must list explicit origins. Wildcard `*` is rejected at startup. Same-origin `/app` static pages avoid CORS on the critical customer path when the UI is served by the API process.

## Secret and log hygiene

- Never commit production `ENCRYPTION_KEY`, database credentials, workspace API keys, Stripe secret keys, webhook signing secrets, or checkout session URLs.
- Use a secrets manager or protected platform environment variables in production.
- Do not log API keys, Stripe secrets, webhook signatures, checkout URLs or session secrets, encryption keys, or memory content.
- Treat bootstrap CLI output as an operator secret and capture it only in a protected secret store.
- Back up encrypted data and encryption keys separately and protect access to both.

## Deployment expectations

Production deployments should use HTTPS, a secured PostgreSQL service, network restrictions, least-privilege database credentials, monitored backups, and platform-level secret protection. Apply `alembic upgrade head` as an explicit deployment step before customer traffic. Application startup is not migration execution.

## Dependency and change policy

Security-sensitive changes should be made through a branch and pull request, with CI passing before merge. Schema changes should use Alembic migrations rather than manual production-table edits.
