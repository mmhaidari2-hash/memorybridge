# Security Policy

MemoryBridge handles application memory and credentials, so security issues should be treated as high priority.

## Supported versions

The current secure-foundation release candidate is `v0.2`. Earlier experimental code should not be treated as production-ready.

## Reporting a vulnerability

Please do not publish a working exploit, production credential, encryption key, or private user data in a public issue.

Until a dedicated private vulnerability-reporting channel is configured, repository owners should enable GitHub Private Vulnerability Reporting before a public production launch.

## Security boundaries

MemoryBridge v0.2 provides:

- AES-256-GCM encryption of memory summaries before database persistence;
- fresh random nonces for each encryption operation;
- one-way hashing of user and session credentials before database storage;
- ownership checks that bind memory records to an internal user identifier;
- fail-closed startup/configuration behavior when required encryption or database configuration is absent;
- input validation and automated security-oriented API tests.

MemoryBridge v0.2 does **not** provide:

- zero-knowledge or end-to-end encryption;
- protection from an attacker who has both the database contents and the live server encryption key;
- automatic encryption-key rotation;
- enterprise identity federation or fine-grained RBAC;
- a compliance certification;
- a guarantee against denial-of-service or credential brute-force attacks before rate limiting is implemented.

## Secret handling

- Never commit production `ENCRYPTION_KEY`, database credentials, user tokens, or session tokens.
- Use a secrets manager or protected platform environment variables in production.
- Treat user and session tokens returned by the API as bearer secrets.
- Avoid logging request bodies or decrypted memory content.
- Back up encrypted data and encryption keys separately and protect access to both.

## Deployment expectations

Production deployments should use HTTPS, a secured PostgreSQL service, network restrictions, least-privilege database credentials, monitored backups, and platform-level secret protection.

## Dependency and change policy

Security-sensitive changes should be made through a branch and pull request, with CI passing before merge. Schema changes should use Alembic migrations rather than manual production-table edits.
