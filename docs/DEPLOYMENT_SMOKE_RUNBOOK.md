# MemoryBridge Deployment Smoke Runbook

Use immediately after every staging or production deployment and before customer traffic.

## 1. Runtime and migration gate
Production uses `APP_ENV=production`; staging uses `BILLING_MODE=test`; Live Mode is allowed only after the sandbox gate. Apply `alembic upgrade head`. Never bypass runtime validation.

## 2. Public deployment smoke
Run externally:
```bash
python scripts/deployment_smoke.py https://YOUR-API.example
MEMORYBRIDGE_API_KEY='mbs_...' python scripts/deployment_smoke.py https://YOUR-API.example
```
Expected: health, readiness, service metadata, customer web entrypoint, and authenticated account control-plane pass. Secrets must never be placed in URLs or evidence logs.

## 3. Browser activation
In a clean/private browser: Landing -> Onboarding -> workspace verification -> **Run first successful memory** -> Dashboard. Require the real store/recall round trip, usage increment, no CORS error, and no credential/token/plaintext-memory leakage in URLs or logs.

## 4. Dashboard
Verify plan/subscription/usage are API-derived; API-key create/list/revoke works; revoked keys stop authenticating; Free exposes upgrade; paid entitlement does not expose a duplicate upgrade path.

## 5. Stripe Test Mode checkout smoke
Only with `BILLING_MODE=test`, Test Mode Stripe credentials, and a disposable workspace:
```bash
MEMORYBRIDGE_API_KEY='mbs_...' SMOKE_STRIPE_CHECKOUT=1 \
python scripts/deployment_smoke.py https://YOUR-STAGING-API.example
```
The smoke script creates Pro and Team Checkout Sessions and requires Stripe-hosted checkout URLs. It does **not** complete payment, print checkout URLs/session IDs, or grant entitlement. Never enable this probe against Live Mode merely to obtain a green smoke result.

Then manually/browser-test the customer path: Onboarding -> Dashboard -> Pro/Team checkout -> Stripe Test Checkout -> configured success redirect -> Dashboard. The redirect itself must not change entitlement.

## 6. Stripe webhook synchronization gate
The application must handle these signed events with the following invariants:

- `checkout.session.completed`: persist trusted Stripe customer/subscription identifiers; **never grant paid entitlement**.
- `customer.subscription.created|updated`: authoritative plan/status synchronization; only `pro`/`team` and active/trialing grant paid entitlement.
- `invoice.payment_succeeded`: synchronize billing health only for an already-established paid subscription; it cannot invent a paid plan.
- `invoice.payment_failed`: mark billing health `past_due` without granting access. Subscription lifecycle remains authoritative for entitlement removal.
- `customer.subscription.deleted`: downgrade to `free` and record canceled status.
- duplicate event IDs: idempotent, one `BillingEvent` only.
- missing/invalid signature: HTTP 400 and zero billing/entitlement database writes.
- malformed/invalid-plan event: rollback the `BillingEvent` and all tenant mutations.

Use Stripe Test Mode/CLI or Dashboard webhook delivery to send genuine signed events to staging. Unit tests mock signature construction to exercise state transitions; they do not replace a genuine signed staging delivery.

## 7. Failure-path gate
Before external paid traffic, prove in staging:

1. cancel/abandon a Checkout Session: account remains unchanged;
2. allow a Test Checkout Session to expire or use an invalid/old session URL: no entitlement is granted;
3. POST a webhook without a valid Stripe signature: HTTP 400, no DB mutation;
4. simulate failed payment: no paid entitlement is created;
5. deliver the same signed event twice: second delivery is harmless/idempotent;
6. cancel the subscription: account returns to Free after the signed subscription deletion event.

## 8. Evidence record
Record: commit SHA, environment, API/web origin, migration result, smoke result, First Successful Memory result, Dashboard result, `BILLING_MODE`, Pro checkout PASS, Team checkout PASS, genuine signed webhook PASS, duplicate PASS, invalid-signature PASS, payment-failure PASS, cancellation PASS, CI run, operator/date. Never record API keys, Stripe secrets, webhook secrets, checkout URLs/session IDs, user/session tokens, or memory content.

## Stop conditions
Do not invite external paid customers when readiness/HTTPS/activation/API-key lifecycle fails; account state disagrees with backend; checkout works but signed webhook lifecycle is unproven; invalid webhook can mutate DB; payment failure can grant access; cancellation fails to downgrade; deployed commit CI is not green; or Stripe Test Mode end-to-end evidence is incomplete.
