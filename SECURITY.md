# Security Policy

MemoryBridge handles application memory and credentials, so security issues should be treated as high priority.

## Supported versions

The current commercial-foundation release candidate is `v0.4`. Earlier experimental code should not be treated as production-ready for multi-tenant customers.

## Reporting a vulnerability

Please do not publish a working exploit, production credential, encryption key, or private user data in a public issue.

Until a dedicated private vulnerability-reporting channel is configured, repository owners should enable GitHub Private Vulnerability Reporting before a public production launch.

## Security boundaries

MemoryBridge v0.4 provides:

- AES-256-GCM encryption of memory summaries before database persistence;
- encryption key versioning for rotation-friendly deployments;
- AAD binding of ciphertext to tenant + user identifiers;
- peppered HMAC-SHA256 hashing of user and session credentials;
- durable hashed service API keys with revocation;
- tenant isolation for users, memories, keys, and audit events;
- ownership checks that bind memory records to tenant + internal user IDs;
- fail-closed startup when required security configuration is absent;
- per-key rate limiting, security headers, request-size guards, and privacy-safe logs;
- append-only audit events that exclude secrets and memory content;
- input validation and automated security-oriented API tests.

MemoryBridge v0.4 does **not** provide:

- zero-knowledge or end-to-end encryption;
- protection from an attacker who has both the database contents and the live server encryption keys;
- automatic online re-encryption of all historical rows after key rotation;
- enterprise identity federation (OIDC/SAML) or fine-grained RBAC beyond tenant/admin split;
- a compliance certification (SOC2/ISO) by itself;
- distributed rate limiting across horizontally scaled replicas (process-local today).

## Secret handling

- Never commit production `ENCRYPTION_KEY` / `ENCRYPTION_KEYS`, `TOKEN_HASH_PEPPER`, database credentials, admin keys, user tokens, or session tokens.
- Use a secrets manager or protected platform environment variables in production.
- Treat user and session tokens returned by the API as bearer secrets.
- Treat service API keys and admin API keys as bearer secrets; revoke compromised DB-backed keys immediately.
- Avoid logging request bodies or decrypted memory content.
- Back up encrypted data and encryption keys separately and protect access to both.

## Tenant and key model

- Each customer should receive a dedicated tenant.
- Issue durable service API keys per tenant via the admin API; prefer these over long-lived env bootstrap keys.
- Env `SERVICE_API_KEYS` remain available for bootstrap/break-glass against the default tenant only.
- Suspend tenants to immediately block authentication for their durable keys.

## Deployment expectations

Production deployments should use HTTPS, a secured PostgreSQL service, network restrictions, least-privilege database credentials, monitored backups, platform-level secret protection, and separate storage of encryption key material.

## Dependency and change policy

Security-sensitive changes should be made through a branch and pull request, with CI passing before merge. Schema changes should use Alembic migrations rather than manual production-table edits.
