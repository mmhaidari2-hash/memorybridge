# MemoryBridge Deployment Smoke Runbook

Use immediately after every staging or production deployment and before customer traffic.

## 1. Runtime and migration gate

Customer-facing staging/production uses `APP_ENV=production`. Staging must remain `BILLING_MODE=test`; Live Mode is allowed only after the sandbox gate. Never bypass runtime validation.

### Required pre-deploy migration

Application startup (`uvicorn`, the Docker `CMD`, or process restart) does **not** run Alembic and must not be treated as schema migration. Before the first request, and after every deploy that can include a schema change, run this as an explicit operator step against the target database:

```bash
alembic upgrade head
```

Expected current head: `0005_billing_state` (tenants/workspaces, workspace API keys, usage events, and billing state). Do not start or smoke-test the API if this command fails.

If migration fails:

1. Keep the application off customer traffic. Do not start checkout or webhook traffic against a half-migrated database.
2. Capture the Alembic error and the current `alembic current` revision. Do not paste database credentials into that record.
3. Do not hand-edit production tables to “finish” a failed revision.
4. Restore the previous known-good application commit and, if the schema change is unsafe, restore the previous known-good database snapshot.
5. Re-run `alembic current` and `alembic upgrade head` only after the revision is fixed.
6. Re-run `/ready` and `scripts/deployment_smoke.py` only after migration reports success.

### First-workspace operator bootstrap

Onboarding does not create a tenant or API key. After a successful `alembic upgrade head`, an operator bootstraps the first Staging workspace with the CLI. There is no public HTTP provisioning endpoint.

```bash
python scripts/bootstrap_workspace.py \
  --tenant-name "Staging Tenant" \
  --workspace-name "Staging Workspace"
```

The command prints the plaintext `mbs_...` workspace API key **once**. Store it in a secrets manager or a local operator secret store, then use it for onboarding and `MEMORYBRIDGE_API_KEY`.

**Warning:** Do not paste the plaintext API key into GitHub, logs, tickets, screenshots, CI output, evidence records, or committed files. If it is exposed, revoke it after creating a replacement with a still-valid workspace key, or bootstrap a fresh disposable workspace.

A second run with the same tenant name or workspace name/slug fails closed and does not print a new key. Use the existing key or choose distinct names.

### Exact Stripe staging environment variables

MemoryBridge uses the same variable names for Test and Live Mode; **there are no `STRIPE_TEST_*` aliases**. For staging set these exact names:

```text
APP_ENV=production
BILLING_MODE=test
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_...       # Stripe Test Mode Pro recurring price
STRIPE_PRICE_TEAM=price_...      # Stripe Test Mode Team recurring price
BILLING_SUCCESS_URL=https://YOUR-STAGING-HOST/app/dashboard.html?billing=success
BILLING_CANCEL_URL=https://YOUR-STAGING-HOST/app/dashboard.html?billing=cancel
CORS_ALLOWED_ORIGINS=https://YOUR-STAGING-HOST
```

The deployment also still requires the normal production variables, especially `DATABASE_URL` and a valid 32-byte-base64 `ENCRYPTION_KEY`. `STRIPE_PRICE_PRO` and `STRIPE_PRICE_TEAM` must be different Test Mode `price_` IDs. Never place Stripe secrets in Git, URLs, screenshots, CI output, or this evidence record.

## 2. Public deployment smoke

Run externally:

```bash
python scripts/deployment_smoke.py https://YOUR-STAGING-API.example
MEMORYBRIDGE_API_KEY='mbs_...' python scripts/deployment_smoke.py https://YOUR-STAGING-API.example
```

Expected: health, readiness, service metadata, customer web entrypoint, and authenticated account control-plane pass. Secrets must never be placed in URLs or evidence logs.

## 3. Browser activation

In a clean/private browser: Landing -> Onboarding -> workspace verification -> **Run first successful memory** -> Dashboard. Require the real store/recall round trip, usage increment, no CORS error, and no credential/token/plaintext-memory leakage in URLs or logs.

## 4. Dashboard

Verify plan/subscription/usage are API-derived; API-key create/list/revoke works; revoked keys stop authenticating; Free exposes upgrade; paid entitlement does not expose a duplicate upgrade path.

## 5. Stripe Test Mode checkout smoke

Only with the exact staging variables above and a disposable workspace:

```bash
MEMORYBRIDGE_API_KEY='mbs_...' \
SMOKE_STRIPE_CHECKOUT=1 \
python scripts/deployment_smoke.py https://YOUR-STAGING-API.example
```

Before creating a session, the smoke script authenticates to `GET /v1/billing/status` and requires `mode=test`, `checkout_configured=true`, and `webhook_configured=true`. It then creates Pro and Team Checkout Sessions and requires Stripe-hosted checkout URLs. It does **not** print checkout URLs/session IDs, complete payment, or grant entitlement. If the deployed service reports any mode other than `test`, the probe fails closed and refuses checkout creation.

Then manually/browser-test the customer path: Onboarding -> Dashboard -> Pro/Team checkout -> Stripe Test Checkout -> configured success redirect -> Dashboard. The redirect itself must not change entitlement.

## 6. Genuine signed staging webhook gate

The canonical staging endpoint is:

```text
POST https://YOUR-STAGING-API.example/v1/billing/webhook
```

### Preferred: Stripe Dashboard Test Mode endpoint

In Stripe **Test Mode**, create a webhook destination pointing to the staging endpoint above. Subscribe at minimum to:

```text
checkout.session.completed
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
invoice.payment_succeeded
invoice.payment_failed
```

Copy that endpoint's signing secret (`whsec_...`) into staging as `STRIPE_WEBHOOK_SECRET`, redeploy/restart, then complete a real Test Mode subscription through MemoryBridge Checkout. Do not manually manufacture entitlement in the database. The normal Stripe event chain should deliver signed events to staging.

After payment, verify with the same workspace key:

```bash
curl -sS \
  -H 'X-MemoryBridge-Key: mbs_...' \
  https://YOUR-STAGING-API.example/v1/account/status
```

Required result: after the authoritative subscription event, `paid_entitlement_active=true`, the selected plan is reported, and the subscription state is active/trialing. `checkout.session.completed` alone must never produce that result.

### Optional temporary Stripe CLI path

For an operator-controlled temporary test, authenticate Stripe CLI to the Test Mode account and run:

```bash
stripe listen \
  --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.payment_succeeded,invoice.payment_failed \
  --forward-to https://YOUR-STAGING-API.example/v1/billing/webhook
```

`stripe listen` prints a temporary `whsec_...`. The staging application must use **that exact temporary signing secret** while this listener is the sender; a Dashboard endpoint signing secret will not validate CLI-forwarded signatures. Restore the persistent Dashboard webhook secret afterward.

Use a real MemoryBridge Test Checkout whenever possible. Generic `stripe trigger` fixtures may not contain MemoryBridge tenant/plan metadata and are therefore expected to fail closed instead of granting entitlement.

## 7. Webhook synchronization invariants

- `checkout.session.completed`: persist trusted Stripe customer/subscription identifiers; **never grant paid entitlement**.
- `customer.subscription.created|updated`: authoritative plan/status synchronization; only `pro`/`team` and active/trialing grant paid entitlement.
- `invoice.payment_succeeded`: synchronize billing health only for an already-established paid subscription; it cannot invent a paid plan.
- `invoice.payment_failed`: mark billing health `past_due` without granting access. Subscription lifecycle remains authoritative for entitlement removal.
- `customer.subscription.deleted`: downgrade to `free` and record canceled status.
- duplicate event IDs: idempotent, one `BillingEvent` only.
- missing/invalid signature: HTTP 400 and zero billing/entitlement database writes.
- malformed/invalid-plan event: rollback the `BillingEvent` and all tenant mutations.

Unit tests mock signature construction to exercise state transitions; they do not replace a genuine signed staging delivery.

## 8. Failure-path gate

Before external paid traffic, prove in staging:

1. cancel/abandon a Checkout Session: account remains unchanged;
2. allow a Test Checkout Session to expire or use an invalid/old session URL: no entitlement is granted;
3. POST a webhook without a valid Stripe signature: HTTP 400, no DB mutation;
4. simulate failed payment: no paid entitlement is created;
5. deliver the same signed event twice: second delivery is harmless/idempotent;
6. cancel the subscription: account returns to Free after the signed subscription deletion event.

## 9. Final evidence run

After staging variables and the genuine signed webhook endpoint are configured, run:

```bash
MEMORYBRIDGE_API_KEY='mbs_...' \
SMOKE_STRIPE_CHECKOUT=1 \
python scripts/deployment_smoke.py https://YOUR-STAGING-API.example
```

A valid final smoke report must contain PASS for the deployment checks plus both Pro and Team Test Mode session creation. Then record the genuine signed webhook/account-sync result separately; `deployment_smoke.py` intentionally does not fake or auto-complete a payment.

Record: commit SHA, environment, API/web origin, migration result, smoke result, First Successful Memory result, Dashboard result, `BILLING_MODE`, Pro checkout PASS, Team checkout PASS, genuine signed webhook PASS, duplicate PASS, invalid-signature PASS, payment-failure PASS, cancellation PASS, CI run, operator/date. Never record API keys, Stripe secrets, webhook secrets, checkout URLs/session IDs, user/session tokens, or memory content.

## Stop conditions

Do not invite external paid customers when readiness/HTTPS/activation/API-key lifecycle fails; account state disagrees with backend; checkout works but signed webhook lifecycle is unproven; invalid webhook can mutate DB; payment failure can grant access; cancellation fails to downgrade; deployed commit CI is not green; or Stripe Test Mode end-to-end evidence is incomplete.
